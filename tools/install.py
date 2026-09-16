#!/usr/bin/env python3
"""Installs Greffier on macOS, Linux or Windows.

    python3 tools/install.py            # checks, offers, installs
    python3 tools/install.py --oui      # without asking anything
    python3 tools/install.py --verifier # only reports

Written with the standard library only: it has to run *before* anything is
installed, so it can depend on nothing. Compatible with Python 3.9, the
version still shipped by default on many machines.

The script detects what is missing and installs it, rather than printing a
list of commands to copy. Every installation is announced and, except with
« --oui », asks for confirmation: nobody likes a script touching their
machine unannounced. What it prints is for the person installing, in French;
the code around it is in English.
"""

import argparse
import contextlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEM = platform.system()  # Darwin | Linux | Windows

# --------------------------------------------------------------------- sortie

# The default Windows console is cp1252: it can write neither « ✓ » nor « é ».
# Without this switch the installer dies on a UnicodeEncodeError on its very
# first line, before saying what it is for.
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        with contextlib.suppress(OSError, ValueError):
            _flux.reconfigure(encoding="utf-8", errors="replace")


def _printable(symbole):
    """Does the symbol fit in the console's encoding?"""
    try:
        symbole.encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Plain ASCII fallback for consoles that accept nothing else.
SYMBOLS = (
    {"ok": "✓", "warn": "⚠", "error": "✗"}
    if _printable("✓⚠✗")
    else {"ok": "[ok]", "warn": "[!]", "error": "[X]"}
)

COLOURS = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _tint(code, text):
    return f"\033[{code}m{text}\033[0m" if COLOURS else text


def title(text):
    print(_tint("1;34", f"\n{text}"))


def ok(text):
    print(_tint("0;32", f"  {SYMBOLS['ok']} {text}"))


def warn(text):
    print(_tint("0;33", f"  {SYMBOLS['warn']} {text}"))


def error(text):
    print(_tint("0;31", f"  {SYMBOLS['error']} {text}"), file=sys.stderr)


def info(text):
    print(f"    {text}")


def make_folder(path):
    """Creates a folder, first removing a dead link that would hold its name.

    `mkdir(parents=True, exist_ok=True)` does not cover a symbolic link whose
    target is gone: the name is taken, `is_dir()` answers no, and the error
    comes back as a stack trace in the middle of the installation. The case is
    a real one -- `~/.claude/skills` pointed into a repository since moved, and
    the installer stopped there, after the models and the dependencies were in
    place, saying nothing about what was missing.

    A link that leads nowhere protects nothing: it goes, and is said to go. A
    link to a folder that exists is a choice of the person installing and is
    left alone.
    """
    for ancestor in [*reversed(path.parents), path]:
        if ancestor.is_symlink() and not ancestor.exists():
            info(f"lien mort écarté : {ancestor} → {os.readlink(ancestor)}")
            ancestor.unlink()
    path.mkdir(parents=True, exist_ok=True)


class Abort(Exception):
    """Stops the installation with an actionable message."""


# ----------------------------------------------------------------- decisions

class Context:
    def __init__(self, args):
        self.yes = args.yes
        self.check_only = args.check
        self.models = Path(
            args.models or os.environ.get("GREFFIER_MODELES") or data_folder() / "modeles"
        )
        self.config = Path(
            args.config or os.environ.get("GREFFIER_CONFIG") or config_folder()
        )
        # An earlier chain may already hold the models: taking them beats
        # fetching 1.6 GB again. Emptied to test from nothing.
        reprise = os.environ.get("GREFFIER_MODELES_EXISTANTS", str(Path.home() / "reunions/models"))
        self.reprise = Path(reprise) if reprise else None
        self.to_do = []

    def ask(self, question):
        if self.check_only:
            return False
        if self.yes:
            return True
        if not sys.stdin.isatty():
            # Without a terminal (CI, a script), install nothing on the quiet.
            warn(f"{question} : passé (pas de terminal ; utilise --oui)")
            return False
        return input(f"    {question} [o/N] ").strip().lower() in {"o", "oui", "y", "yes"}


# The locations are the application's, read from its module without any
# dependency: the installer runs before the package is installed, hence the
# loading by path. One definition only, so that the installer and the tool
# cannot contradict each other on where the models live.
def _load_locations():
    specification = importlib.util.spec_from_file_location(
        "greffier_locations", ROOT / "src/greffier/locations.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


LOCATIONS = _load_locations()


def data_folder():
    return LOCATIONS.data_folder(SYSTEM)


def config_folder():
    return LOCATIONS.config_folder(SYSTEM)


def locations_step():
    """Moves out of ~/.config and ~/.local what a previous version left there.

    macOS only: the account's hidden folders are watched by the machine's
    guards, which asked for an authorisation again at every access, up to
    refusing a write in the middle of a meeting. Everything now lives in
    Application Support. Does nothing elsewhere, nor when there is nothing
    to move.
    """
    deplaces = LOCATIONS.relocate(SYSTEM)
    if not deplaces:
        return
    title("0. Emplacements")
    for source, target in deplaces:
        ok(f"{source} → {target}")


def run_job(command, **kwargs):
    """Runs a command while showing what is launched."""
    info(f"$ {' '.join(command)}")
    return subprocess.run(command, check=False, **kwargs)


# ------------------------------------------------- gestionnaires de paquets

def nvidia_card():
    """Whether the machine has an NVIDIA card the transcription could use.

    macOS has none, and its chip is already served by Metal.
    """
    return SYSTEM != "Darwin" and shutil.which("nvidia-smi") is not None


SHERPA_CUDA = "1.13.7"


def sherpa_cuda_wheel(system, marqueur, machine):
    """The address of the sherpa-onnx wheel that talks to the card, or None.

    Cutting into speaker turns runs the voiceprint model on every excerpt,
    and that model weighs a hundred megabytes: measured on a 40.7 s meeting,
    43 s on the processor against 5.8 s on the card, with identical turns
    returned. It is the first cost item of the processing. No PyPI wheel can
    address the card; this one comes from the release repository of the
    sherpa-onnx project.
    """
    if system == "Linux" and machine == "x86_64":
        end = f".onnxruntime1.27.1-{marqueur}-{marqueur}-linux_x86_64.whl"
    elif system == "Windows" and machine in ("AMD64", "x86_64"):
        end = f"-{marqueur}-{marqueur}-win_amd64.whl"
    else:
        return None
    return (
        "https://huggingface.co/csukuangfj2/sherpa-onnx-wheels/resolve/main/cuda/"
        f"{SHERPA_CUDA}/sherpa_onnx-{SHERPA_CUDA}%2Bcuda12.cudnn9{end}"
    )


def _python_tag(python):
    """« cp313 » and the machine, asked of the environment's interpreter."""
    done = run_job(
        [str(python), "-c",
         "import platform,sys;"
         "print(f'cp{sys.version_info.major}{sys.version_info.minor}');"
         "print(platform.machine())"],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        return None, None
    lines = done.stdout.split()
    return (lines[0], lines[1]) if len(lines) == 2 else (None, None)


def card_step(ctx, python):
    """Replaces sherpa-onnx with the version that uses the card."""
    if not nvidia_card():
        return
    marqueur, machine = _python_tag(python)
    if marqueur is None:
        return
    url = sherpa_cuda_wheel(SYSTEM, marqueur, machine)
    if url is None:
        return
    if ctx.check_only:
        return
    if not ctx.ask("Accélérer le découpage en tours de parole sur la carte ? "
                   "(260 Mo, sept fois plus rapide)"):
        ctx.to_do.append(f"uv pip install '{url}'")
        return
    command = (["uv", "pip", "install", "-q", url]
                if shutil.which("uv") else
                [str(python), "-m", "pip", "install", "-q", url])
    done = run_job(command, cwd=ROOT)
    if done.returncode == 0:
        ok("découpage accéléré par la carte")
    else:
        warn("la roue CUDA de sherpa-onnx n'a pas pu être installée ; "
               "le découpage restera sur le processeur")


def sound_server_present():
    """Whether the session has a sound server to plug into.

    « pactl » records nothing: it queries the server, where ffmpeg plugs
    straight into its socket. Judging the capture on that tool declared lost
    a machine perfectly able to record, PipeWire running, but
    « pulseaudio-utils » never installed.
    """
    if os.environ.get("PULSE_SERVER"):
        return True
    execution = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return (Path(execution) / "pulse" / "native").exists()


#: The languages the tool offers, read from the package rather than copied:
#: three copies of one list are three chances for them to
#: contradict each other. Loaded by path, like the locations, because
#: the installer runs before anything at all is installed.
def _load_catalogue():
    """The catalogue of the models, read from the package.

    One list only: the application reads it to offer the missing downloads,
    the installer to put them in place. Two copies would have diverged at
    the first model changed.
    """
    name = "greffier_model_files"
    specification = importlib.util.spec_from_file_location(
        name, ROOT / "src/greffier/adapters/model_files.py"
    )
    module = importlib.util.module_from_spec(specification)
    # Registered before it runs: a dataclass with `slots` looks its own module
    # up in sys.modules while it is being built, and fails otherwise.
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _load_languages():
    specification = importlib.util.spec_from_file_location(
        "greffier_langues", ROOT / "src/greffier/domain/languages.py"
    )
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
    except Exception:
        # The module imports the registry of profiles, which does not exist yet on
        # a half-installed repository. The fallback is French, as before.
        return None
    return module


def system_language():
    """The language the system announces, if Greffier can serve it.

    A free piece of information nothing read: a German machine came out set
    to French, and nobody noticed before the first transcription.
    """
    languages = _load_languages()
    known = {code for code, _ in languages.LANGUAGES} if languages else {"fr"}
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "")
        if value:
            code = value.split(".")[0].split("_")[0].lower()
            if code in known:
                return code
    return "fr"


def package_manager():
    """The machine's package manager, or None when none is recognised."""
    if SYSTEM == "Darwin":
        return ("brew", ["brew", "install"]) if shutil.which("brew") else None
    if SYSTEM == "Windows":
        if shutil.which("winget"):
            return ("winget", ["winget", "install", "--accept-package-agreements",
                               "--accept-source-agreements", "-e", "--id"])
        if shutil.which("scoop"):
            return ("scoop", ["scoop", "install"])
        return None
    # In a container or on a continuous integration runner everything runs as
    # root, where « sudo » is often not even installed.
    prefixe = [] if getattr(os, "geteuid", lambda: 1)() == 0 else ["sudo"]
    for outil, command in (
        ("apt-get", ["apt-get", "install", "-y"]),
        ("dnf", ["dnf", "install", "-y"]),
        ("pacman", ["pacman", "-S", "--noconfirm"]),
        ("zypper", ["zypper", "install", "-y"]),
        ("apk", ["apk", "add"]),
    ):
        if shutil.which(outil):
            return (outil, prefixe + command)
    return None


# The package name per manager: ffmpeg is called the same everywhere, but
# not everything is.
PACKAGES = {
    "ffmpeg": {
        "brew": "ffmpeg", "apt-get": "ffmpeg", "dnf": "ffmpeg", "pacman": "ffmpeg",
        "zypper": "ffmpeg", "apk": "ffmpeg",
        "winget": "Gyan.FFmpeg", "scoop": "ffmpeg",
    },
    "whisper-cpp": {
        # Packaged by Homebrew only. Elsewhere the transcription goes through
        # faster-whisper, installed in the Python environment.
        "brew": "whisper-cpp",
    },
    "ollama": {
        "brew": "ollama", "winget": "Ollama.Ollama", "scoop": "ollama",
    },
    "uv": {
        "brew": "uv", "winget": "astral-sh.uv", "scoop": "uv",
    },
}


def install_package(ctx, name, because):
    gest = package_manager()
    if gest is None:
        warn(f"{name} absent, et aucun package_manager de paquets reconnu sur ce poste")
        info(f"Installe-le à la main : {because}")
        return False
    outil, command = gest
    package = PACKAGES.get(name, {}).get(outil)
    if package is None:
        warn(f"{name} n'est pas empaqueté par {outil}")
        return False
    if not ctx.ask(f"Installer {name} avec {outil} ? ({because})"):
        ctx.to_do.append(f"{' '.join(command)} {package}")
        return False
    if outil == "apt-get":
        # Without a refresh, apt fails on an image or a machine whose package
        # list has never been updated.
        run_job(command[:-2] + ["update", "-qq"], stdout=subprocess.DEVNULL)
    return run_job(command + [package]).returncode == 0


# ----------------------------------------------------------- 1. system tools

def system_tools_step(ctx):
    title("1. Outils système")

    if shutil.which("ffmpeg"):
        ok("ffmpeg")
    elif not install_package(ctx, "ffmpeg", "enregistrement et conversion audio"):
        raise Abort("ffmpeg est indispensable : sans lui, rien ne peut être enregistré.")

    # whisper.cpp speeds the transcription up on the graphics chip, but
    # only exists as a package on macOS. Its absence does not block anything:
    # faster-whisper takes over, in Python, on all three systems.
    if shutil.which("whisper-cli") or shutil.which("whisper"):
        ok("whisper.cpp (transcription accélérée)")
        return "whisper.cpp"
    if SYSTEM == "Darwin" and install_package(
        ctx, "whisper-cpp", "transcription accélérée Metal"
    ):
        ok("whisper.cpp")
        return "whisper.cpp"
    warn("whisper.cpp absent, la transcription passera par faster-whisper (Python)")
    return "faster-whisper"


# ---------------------------------------------------------- 2. capture audio

def audio_step(ctx):
    """Checks what there is to capture the other attendees' sound with.

    It is the only point that really differs from one system to another:
    hearing one's own voice is trivial, recording again what the speakers
    play is not.
    """
    title("2. Capture du son des autres participants")

    if SYSTEM == "Darwin":
        output = subprocess.run(
            ["system_profiler", "SPAudioDataType"], capture_output=True, text=True, check=False
        ).stdout
        if "BlackHole" in output:
            ok("BlackHole (pilote audio virtuel)")
        else:
            warn("BlackHole absent : sans lui, seule ta voix serait enregistrée")
            if ctx.ask("Installer BlackHole ? (mot de passe admin demandé)"):
                run_job(["brew", "install", "--cask", "blackhole-2ch"])
                info("Puis : sudo killall coreaudiod   (recharge le son, coupure de 1-2 s)")
            else:
                ctx.to_do.append("brew install --cask blackhole-2ch")
                ctx.to_do.append("sudo killall coreaudiod")
        return

    if SYSTEM == "Linux":
        # PipeWire and PulseAudio already expose a « monitor » of the output:
        # nothing to install, unlike macOS.
        if sound_server_present():
            ok("PulseAudio/PipeWire : le moniteur de sortie sert de capture")
            info("Aucun pilote supplémentaire n'est nécessaire sur Linux.")
        else:
            warn("aucun serveur de son : le son des autres participants ne pourra pas"
                   " être capté")
            info("Sur un poste de bureau, installe « pipewire-pulse » ou « pulseaudio ».")
            info("En conteneur ou sur un serveur, c'est normal : seule l'analyse de")
            info("fichiers déjà enregistrés est possible.")
        return

    ok("WASAPI (capture de boucle intégrée à Windows)")
    info("ffmpeg capte la sortie via « -f dshow » ou la boucle WASAPI.")


# ----------------------------------------------------------------- 3. models

MODELS = [
    {
        "nom": "ggml-large-v3-turbo.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        "taille_min": 1_000_000_000,
        "role": "transcription",
        "requis_si": "whisper.cpp",
    },
    {
        "nom": "ggml-silero-v5.1.2.bin",
        "url": "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin",
        "taille_min": 500_000,
        "role": "détection de la parole",
        "requis_si": "whisper.cpp",
    },
    {
        # The live model. It transcribes a ten-second slice in a fraction of a
        # second where the large one takes several: during a meeting a slice has
        # to be returned before the next one is recorded, or the display falls
        # behind and never catches up. Optional; without it the live thread
        # falls back on the large model.
        "nom": "ggml-small.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "taille_min": 400_000_000,
        "role": "transcription en direct",
        "requis_si": "whisper.cpp",
    },
    {
        "nom": "diarisation/nemo_en_titanet_large.onnx",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
               "speaker-recongition-models/nemo_en_titanet_large.onnx",
        "taille_min": 20_000_000,
        "role": "empreintes vocales",
    },
]

SEGMENTATION = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)

# The assistant's voice, when it takes part in the meeting. A French VITS,
# driven by the sherpa-onnx already installed for the segmentation: no new
# dependency, no network call.
#
# Chosen by ear against three others, including the multilingual Kokoro that
# until then. It wins on both counts: more natural, and **forty-eight
# times real time** against five: four seconds of speech computed in eight
# hundredths, where the other took almost a second. Eighty megabytes against
# three hundred and twenty-five.
#
# Optional. Without it the assistant falls back on the system voice, which is
# shipped everywhere and audibly synthetic: workable, but not something to show
# anybody. It is therefore the only model downloaded for the way it sounds
# rather than for what it does, and the first to go from a cramped install.
VOICE_RELEASE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
)


def _load_spoken_language():
    """The module that says which voice goes with which language.

    Loaded by literal path, like the list of languages: this installer runs
    before anything is installed, and a table copied here would be a table
    that diverges.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "greffier_tongue", ROOT / "src/greffier/domain/tongue.py"
        )
        module = importlib.util.module_from_spec(spec)
        # Registered before it runs: a « dataclass(slots=True) » rebuilds
        # itself by looking its own module up in sys.modules, and finds
        # nothing when a file is loaded by its path.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a missing voice does not stop an installation
        return None
    return module


def voice_for(language):
    """The voice archive for this language, and what it weighs."""
    module = _load_spoken_language()
    if module is None:
        return None
    return module.voice_for(language)

#: What a voice archive may hold without serving French: the lexicons and
#: grammars of other languages, which the multilingual model dragged along.
#: Absent from a French model, hence the forgiving removal.
USELESS_VOICE_FILES = ("lexicon-gb-en.txt", "lexicon-us-en.txt", "lexicon-zh.txt",
                 "date-zh.fst", "number-zh.fst", "phone-zh.fst")


def link_or_copy(source, target, folder=False):
    """Links the source to the target, or copies it when the system refuses.

    Windows only allows symbolic links in developer mode or in an elevated
    session. Copying costs space, but a 98 MB model duplicated beats an
    installation that fails.
    """
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    try:
        target.symlink_to(source, target_is_directory=folder)
        return "relié à"
    except (OSError, NotImplementedError):
        if folder:
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        return "copié depuis"


def download(url, target):
    """Downloads while showing progress, without leaving a truncated file."""
    partial = target.with_suffix(target.suffix + ".partiel")
    with urllib.request.urlopen(url) as stream, open(partial, "wb") as output:
        total = int(stream.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            output.write(chunk)
            received += len(chunk)
            if total and sys.stdout.isatty():
                print(f"\r    {target.name} {received * 100 // total:3d} %", end="", flush=True)
    if sys.stdout.isatty():
        print("\r", end="")
    # Renamed only once complete: a dropped connection must not leave a
    # truncated model that would fail much later, while running.
    partial.replace(target)


def models_step(ctx, engine):
    title("3. Modèles locaux")
    make_folder(ctx.models / "diarisation")

    for model in MODELS:
        if model.get("requis_si") and model["requis_si"] != engine:
            continue
        target = ctx.models / model["nom"]
        if target.exists() and target.stat().st_size >= model["taille_min"]:
            ok(f"{target.name} ({model['role']})")
            continue
        former = ctx.reprise / model["nom"] if ctx.reprise else None
        if former and former.exists() and former.stat().st_size >= model["taille_min"]:
            comment = link_or_copy(former, target)
            ok(f"{target.name} {comment} {former}")
            continue
        if ctx.check_only:
            warn(f"{target.name} manquant ({model['role']})")
            continue
        info(f"téléchargement de {target.name} ({model['role']})…")
        download(model["url"], target)
        ok(target.name)

    _install_segmentation(ctx)
    _install_voice(ctx)


def _install_segmentation(ctx):
    """The model that spots when somebody speaks. That one is required."""
    folder = ctx.models / "diarisation/sherpa-onnx-pyannote-segmentation-3-0"
    if (folder / "model.onnx").exists():
        ok("modèle de segmentation")
        return
    former = (
        ctx.reprise / "diarisation/sherpa-onnx-pyannote-segmentation-3-0"
        if ctx.reprise else None
    )
    if former and (former / "model.onnx").exists():
        comment = link_or_copy(former, folder, folder=True)
        ok(f"modèle de segmentation {comment} {former}")
        return
    if ctx.check_only:
        warn("modèle de segmentation manquant")
        return
    archive = ctx.models / "diarisation/segmentation.tar.bz2"
    info("téléchargement du modèle de segmentation…")
    download(SEGMENTATION, archive)
    with tarfile.open(archive, "r:bz2") as package:
        if sys.version_info >= (3, 12):
            package.extractall(ctx.models / "diarisation", filter="data")
        else:
            package.extractall(ctx.models / "diarisation")  # noqa: S202
    archive.unlink()
    ok("modèle de segmentation")


def voice_present(folder):
    """A network and its vocabulary, whatever the file name.

    Looking for « model.onnx » only held for Kokoro: a VITS names its weights
    after its voice (« fr_FR-upmc-medium.onnx »). The installation therefore
    announced the voice missing while it was in place, and offered to
    download it again at every pass. Same criterion as the adapter, so that
    the two cannot contradict each other.
    """
    return any(folder.glob("*.onnx")) and (folder / "tokens.txt").exists()


def _install_voice(ctx):
    """The assistant's voice. Optional: its absence stops nothing.

    A failure here must not fail an installation otherwise complete: the tool
    records, transcribes and writes without ever opening its mouth, and that
    is even its default mode.
    """
    folder = ctx.models / "voix"
    if voice_present(folder):
        ok("voix de l'assistant")
        return
    if ctx.check_only:
        warn("voix de l'assistant manquante (il se repliera sur celle du système)")
        return
    voice = voice_for(system_language())
    if voice is None:
        warn(f"aucune voix pour « {system_language()} » : l'assistant parlera "
               "avec celle du système.")
        return
    archive = ctx.models / "voix.tar.bz2"
    info(f"téléchargement de la voix de l'assistant ({voice.weight_mb} Mo, "
         f"{voice.language})…")
    try:
        download(VOICE_RELEASE + voice.archive + ".tar.bz2", archive)
        with tarfile.open(archive, "r:bz2") as package:
            if sys.version_info >= (3, 12):
                package.extractall(ctx.models, filter="data")
            else:
                package.extractall(ctx.models)  # noqa: S202
        extracted = ctx.models / voice.archive
        if extracted.exists():
            if folder.exists():
                shutil.rmtree(folder)
            extracted.rename(folder)
        for useless in USELESS_VOICE_FILES:
            (folder / useless).unlink(missing_ok=True)
        ok("voix de l'assistant")
    except (OSError, tarfile.TarError) as trouble:
        warn(f"voix de l'assistant non installée ({trouble}) : "
               "l'assistant parlera avec la voix du système.")
    finally:
        archive.unlink(missing_ok=True)


# ------------------------------------------------------- 4. writing it up

# Local models accepted, in order of preference: whatever is already on the
# machine is reused before offering a download of several gigabytes. The
# criterion is the quality of the French summary at a reasonable size.
OLLAMA_FAMILIES = ("qwen3", "mistral-small", "gemma3", "llama3.1", "qwen2.5")
OLLAMA_MODEL = os.environ.get("GREFFIER_MODELE_OLLAMA", "qwen3:8b")


def usable_model(disponibles):
    """The first model present that belongs to a recognised family.

    The comparison bears on the start of the name: « qwen3.8 », « qwen3:8b »
    and « qwen3:14b » are the same family, and either will do.
    """
    for famille in OLLAMA_FAMILIES:
        for present in disponibles:
            if present.split(":")[0].replace(".", "").startswith(famille.replace(".", "")):
                return present
    return None


def ollama_models():
    try:
        output = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=False, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split()[0] for line in output.splitlines()[1:] if line.strip()]


def writer_step(ctx):
    """Chooses who writes the minutes.

    Claude Code by default: telling a decision from a hypothesis and tying a
    position to a person stays out of reach of the models that run on a
    laptop. It is the only link of the chain that leaves the machine, and it
    is a deliberate choice.

    Ollama stays pluggable for whoever wants 100 % local, the architecture
    allows it without changing anything else, at the price of a coarser
    summary.
    """
    title("4. Rédaction du compte rendu")

    if shutil.which("claude"):
        ok("Claude Code : rédacteur par défaut")
        info("La transcription sort du poste vers l'API Anthropic ; le reste de la")
        info("chaîne demeure local. Pour ne rien laisser sortir : moteur « ollama ».")
        return {"moteur": "claude", "modele": ""}

    warn("Claude Code absent : c'est le rédacteur par défaut")
    info("Installation : https://claude.com/claude-code")

    if shutil.which("ollama"):
        disponibles = ollama_models()
        found = usable_model(disponibles)
        if found:
            ok(f"Ollama disponible en remplacement : {found} (tout reste local)")
            return {"moteur": "ollama", "modele": found}
        warn(
            f"Ollama installé mais aucun modèle de synthèse reconnu "
            f"({len(disponibles)} présents)"
        )
        if ctx.ask(
            f"Télécharger {OLLAMA_MODEL} pour rédiger en local ? (~5 Go)"
        ) and run_job(["ollama", "pull", OLLAMA_MODEL]).returncode == 0:
            return {"moteur": "ollama", "modele": OLLAMA_MODEL}
        ctx.to_do.append(f"ollama pull {OLLAMA_MODEL}")

    warn("aucun rédacteur : transcription et voix fonctionneront, pas le compte rendu")
    return {"moteur": "aucun", "modele": ""}


WHISPER_MODEL = os.environ.get("GREFFIER_MODELE_WHISPER", "large-v3")


def whisper_model_step(ctx, engine, python):
    """Fetches the faster-whisper model, where whisper.cpp does not exist.

    Without this step everything looks installed and the 1.5 GB download
    starts when the first meeting is launched, that is at the worst moment.
    """
    if engine != "faster-whisper" or ctx.check_only or not python.exists():
        return
    title("5 bis. Modèle de transcription (faster-whisper)")
    info(f"préparation de « {WHISPER_MODEL} »…")
    outcome = subprocess.run(
        [str(python), "-c",
         "from faster_whisper import WhisperModel;"
         f"WhisperModel('{WHISPER_MODEL}', device='cpu', compute_type='int8')"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    if outcome.returncode == 0:
        ok(f"modèle {WHISPER_MODEL} prêt")
    else:
        warn(f"modèle {WHISPER_MODEL} non préparé : il sera récupéré au premier usage")
        latest = outcome.stderr.strip().splitlines()
        if latest:
            info(latest[-1][:160])


# --------------------------------------------------------- 5. environnement

def antialiases(interpreter: str) -> bool | None:
    """Whether this interpreter's Tk smooths text, or None when it cannot be asked.

    Tk answers `xft` when it was built against Xft, and `x11` when it falls back
    to the core bitmap fonts of the eighties. Asking costs a hidden window and a
    tenth of a second; it needs a display, which an installation over ssh does
    not have, hence the third answer.
    """
    if not os.environ.get("DISPLAY") and SYSTEM == "Linux":
        return None
    request = (
        "import tkinter;"
        "r = tkinter.Tk(); r.withdraw();"
        "print(r.tk.eval('tk::pkgconfig get fontsystem'))"
    )
    try:
        done = subprocess.run(
            [interpreter, "-c", request],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip().endswith("xft")


def a_smoothing_interpreter() -> str | None:
    """A Python 3.13+ on this machine whose window would not look like 1989.

    The interpreter uv installs carries its own Tk, built without Xft: the
    window opens, works, and renders every letter without antialiasing -- « les
    textes sont bizarres, comme pas net », reported on sight. A distribution's
    Tk is built with Xft, so a system interpreter is preferred where there is
    one, and only there: on macOS and Windows the shipped Tk smooths already.
    """
    if SYSTEM != "Linux":
        return None
    for name in ("python3.13", "python3.14", "python3.15"):
        path = shutil.which(name)
        if path is None:
            continue
        verdict = antialiases(path)
        if verdict is False:
            continue
        # None means it could not be asked -- no display. A distribution's Tk
        # is built with Xft as a rule, so it is still the better bet.
        if verdict or _has_tkinter(path):
            return path
    return None


def _has_tkinter(interpreter: str) -> bool:
    done = subprocess.run(
        [interpreter, "-c", "import tkinter"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    return done.returncode == 0


def environment_step(ctx, engine):
    title("5. Environnement Python")
    venv = ROOT / ".venv"
    python = venv / ("Scripts/python.exe" if SYSTEM == "Windows" else "bin/python")

    extras = "dev" + (",transcription" if engine == "faster-whisper" else "")
    if engine == "faster-whisper" and nvidia_card():
        # The card alone is not enough: CTranslate2 wants cuBLAS and cuDNN,
        # which no distribution ships with the driver. Without them the
        # transcription falls on the processor, thirteen times slower,
        # thirteen hours for a one-hour meeting.
        if ctx.ask("Installer l'accélération CUDA ? (2,2 Go, la transcription"
                        " passe de treize fois le temps réel à un tiers)"):
            extras += ",cuda"
        else:
            ctx.to_do.append("uv pip install -e '.[cuda]'")

    if ctx.check_only:
        ok("environnement présent") if python.exists() else warn("environnement absent")
        return python

    if SYSTEM == "Darwin" and not shutil.which("uv"):
        # The application carries a relocatable interpreter: only uv installs
        # one (python-build-standalone), and only uv knows how to fill it.
        # Without it the command line works but not the .app bundle.
        install_package(ctx, "uv", "interpréteur relogeable, embarqué dans l'application")

    # The check is on the **interpreter**, never on the folder. A
    # « .venv » that came from another machine, a project folder copied, a
    # backup restored, an image built from a working repository, exists
    # without its interpreter existing: the links it holds point somewhere
    # else. The installation then announced « falling back on venv + pip »,
    # skipped the creation, and fell on « No such file or directory:
    # .venv/bin/python ». Measured: that is what stopped the installation dead
    # on Linux.
    if venv.exists() and not python.exists():
        warn("environnement Python inutilisable (venu d'une autre machine ?), "
               "il est refait")
        shutil.rmtree(venv, ignore_errors=True)

    if shutil.which("uv"):
        if not python.exists():
            lisse = a_smoothing_interpreter()
            if lisse is not None:
                ok(f"interpréteur au texte lissé : {lisse}")
                run_job(["uv", "venv", "--python", lisse], cwd=ROOT)
            else:
                if SYSTEM == "Linux":
                    warn("texte non lissé dans la fenêtre : aucun Python 3.13 "
                           "du système n'a été trouvé")
                    info("« apt install python3.13-tk » (dépôt deadsnakes) le corrige, "
                         "puis relance cette installation.")
                run_job(["uv", "venv", "--python", "3.13"], cwd=ROOT)
        run_job(["uv", "pip", "install", "-q", "-e", f".[{extras}]"], cwd=ROOT)
    else:
        warn("uv absent : repli sur venv + pip, plus lent")
        if not python.exists():
            run_job([sys.executable, "-m", "venv", str(venv)])
        if not python.exists():
            # Stopping here and saying so: the rest would fail anyway,
            # three lines further down, on a Python trace nobody connects to
            # the missing package.
            error("l'environnement Python n'a pas pu être créé. Sous Debian et "
                   "Ubuntu, « apt install python3-venv » le fournit.")
            raise SystemExit(1)
        run_job([str(python), "-m", "pip", "install", "-q", "-e", f".[{extras}]"], cwd=ROOT)
    ok(f"dépendances installées ({extras})")
    card_step(ctx, python)
    return python


# -------------------------------------------------------- 6. configuration

TEMPLATE = '''# Configuration de Greffier. Tout est facultatif : ce qui manque reprend la
# valeur par défaut.

[chemins]
modeles = {models!r}
donnees = {data!r}

[audio]
# Périphériques de capture. Sur macOS, à créer une fois (voir le README) ;
# sur Linux, le moniteur de sortie PipeWire/PulseAudio suffit.
entree = {input!r}
sortie = {output!r}
duree_maximale = 14400        # 4 h : garde-fou contre une réunion oubliée

[transcription]
moteur = {engine!r}           # whisper.cpp (macOS, accéléré) ou faster-whisper
langue = {language!r}
# Noms propres du contexte : c'est ce qui améliore le plus la transcription
# des termes rares.
vocabulaire = ["Jira", "GitLab", "sprint", "merge request", "recette", "backlog"]

[locuteurs]
# Mots à ne jamais prendre pour des prénoms : projets, outils, produits.
pas_des_prenoms = ["Copernic", "Kanban", "Trello"]

[compte_rendu]
# claude : meilleure synthèse, la transcription sort vers l'API Anthropic.
# ollama : tout reste sur le poste, synthèse plus grossière.
moteur = {writer!r}
modele = {model!r}
# Adresse à qui envoyer le compte rendu. Vide = pas d'envoi.
destinataire = ""
'''


def configuration_step(ctx, engine, wording):
    title("6. Configuration")
    make_folder(ctx.config)
    file = ctx.config / "config.toml"
    if file.exists():
        ok(f"configuration existante conservée : {file}")
        return file
    if ctx.check_only:
        warn(f"configuration absente : {file}")
        return file
    file.write_text(
        TEMPLATE.format(
            models=str(ctx.models),
            data=str(data_folder()),
            input="Reunion Entree" if SYSTEM == "Darwin" else "default",
            output="Reunion Sortie" if SYSTEM == "Darwin" else "default.monitor",
            engine=engine,
            language=system_language(),
            writer=wording["moteur"],
            model=wording["modele"],
        ),
        encoding="utf-8",
    )
    ok(f"configuration créée : {file}")
    warn("renseigne « destinataire » pour recevoir les comptes rendus par mail")
    return file


# ------------------------------------------------------ 7. desktop integration

def autostart_folder():
    """Where to put what has to launch when the session opens."""
    if SYSTEM == "Darwin":
        return Path.home() / "Library/LaunchAgents"
    if SYSTEM == "Windows":
        return (Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
                / "Microsoft/Windows/Start Menu/Programs/Startup")
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"


def commands_folder():
    """The personal folder shells carry in their PATH."""
    return Path.home() / ".local/bin"


def applications_folder():
    """Where the desktop menu looks for the user's own entries."""
    return Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")
    ) / "applications"


def greffier_command(python):
    """The launcher the dependency install lays next to the interpreter."""
    return python.parent / ("greffier.exe" if SYSTEM == "Windows" else "greffier")


AGENT_MACOS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>              <string>com.reunions.greffier</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/open</string><string>{target}</string></array>
  <key>RunAtLoad</key>          <true/>
</dict>
</plist>
"""

LINUX_SHORTCUT = """[Desktop Entry]
Type=Application
Name=Greffier
Comment=Enregistre la réunion et en rédige le compte rendu
Exec={target}
Terminal=false
Categories=Office;AudioVideo;
"""

# A .cmd rather than a .lnk: a Windows shortcut is a binary format that needs
# PowerShell and COM to be written, where a script starts just as well and stays
# readable to whoever wants to know what runs at their session.
WINDOWS_STARTUP = """@echo off
rem Lance Greffier à l'ouverture de session. Supprime ce fichier pour l'annuler.
start "" /min {target}
"""


def integrate_with_desktop(ctx, target, write=True):
    """Puts the icon in the bar and the launch at session opening.

    Returns the file written, or None when the system is not recognised. The
    « write » switch makes it possible to check what would be produced on the
    three systems from any machine.
    """
    folder = autostart_folder()
    if SYSTEM == "Darwin":
        file, gabarit = folder / "com.reunions.greffier.plist", AGENT_MACOS
    elif SYSTEM == "Windows":
        file, gabarit = folder / "Greffier.cmd", WINDOWS_STARTUP
    elif SYSTEM == "Linux":
        file, gabarit = folder / "greffier.desktop", LINUX_SHORTCUT
    else:
        return None
    if write:
        make_folder(folder)
        file.write_text(gabarit.format(target=target), encoding="utf-8")
    return file


def install_command(ctx, python):
    """Makes « greffier » callable from any terminal.

    The launcher lives in the repository's `.venv`, which nothing puts in the
    PATH. The installation announced « greffier fenetre » all the same, and the
    README gives the same line: typed after an install that had just declared
    itself finished, it answered `command not found`. The window was there, and
    out of reach unless the environment was activated by hand.

    A link in `~/.local/bin`, which Debian, Ubuntu and Fedora add to the PATH at
    login. A link and not a copy: it follows the repository when the code
    changes, where a copy would freeze the version of the day.
    """
    launcher = greffier_command(python)
    if SYSTEM == "Windows":
        # Nothing equivalent to ~/.local/bin: say where the command is, rather
        # than touch a session PATH, which breaks more easily than it mends.
        info(f"La commande est {launcher} ; ajoute son dossier au PATH.")
        return None

    link = commands_folder() / "greffier"
    already_there = link.is_symlink() and link.exists() and link.resolve() == launcher.resolve()
    if ctx.check_only:
        ok(f"commande « greffier » disponible ({link})") if already_there else warn(
            "commande « greffier » absente du PATH")
        return link if already_there else None
    if already_there:
        ok(f"commande « greffier » disponible ({link})")
    elif not launcher.exists():
        warn("lanceur introuvable dans l'environnement Python")
        return None
    elif not ctx.ask(f"Poser la commande « greffier » dans {link.parent} ?"):
        ctx.to_do.append(f"ln -sf {launcher} {link}")
        return None
    else:
        make_folder(link.parent)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(launcher)
        ok(f"commande « greffier » posée ({link})")

    if str(link.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        info(f"{link.parent} n'est pas dans le PATH de ce terminal : "
             "rouvre-en un, ou ajoute-le à ton profil.")
    return link


def _the_window_can_open(python) -> str | bool | None:
    """What the code itself says of this interpreter's Tk, or None if unasked.

    Asked of the environment that was just built, through the very function the
    window calls before painting: nothing else proves that the window opens.
    """
    if not Path(python).exists():
        return None
    try:
        done = subprocess.run(
            [str(python), "-c",
             "from greffier.interface.startup import available;"
             "possible, raison = available();"
             "print('OUI' if possible else 'NON', raison)"],
            capture_output=True, text=True, cwd=ROOT, check=False, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        # An interpreter that cannot even be run says nothing about a window:
        # the environment step has already reported what it could not build.
        return None
    if done.returncode != 0:
        return None
    said = done.stdout.strip()
    if said.startswith("OUI"):
        return said[4:].strip()
    return False


def desktop_step(ctx, python):
    """Installs the interface: the command in the PATH, the entry in the menu."""
    title("7. Intégration au bureau")

    if SYSTEM == "Darwin":
        if not (ROOT / "macos/construire.sh").exists():
            warn("script de construction introuvable dans ce dépôt")
            return
        # /Applications first: ~/Applications is indexed neither by Spotlight
        # nor by the Launchpad, so an application dropped there does not appear
        # at all. Reported in use: « I have no icon to start it with ».
        candidates = [Path("/Applications/Greffier.app"),
                      Path.home() / "Applications/Greffier.app"]
        application = next((c for c in candidates if c.exists()), candidates[0])
        if ctx.check_only:
            ok(f"application présente ({application})") if application.exists() \
                else warn("application absente")
            return
        # Self-contained and signed with a stable identity (see
        # macos/construire.sh): the microphone and Outlook permissions, granted
        # once, are not asked for again at the next rebuild.
        if run_job([str(ROOT / "macos/construire.sh")]).returncode != 0:
            warn("construction de l'application échouée")
            return
        pose = next((c for c in candidates if c.exists()), None)
        ok(f"application installée ({pose or application})")
        info("Double-clic, ou cherche « Greffier » dans le Launchpad.")
        return

    # Elsewhere the window starts from the command line. Nothing to compile:
    # Tkinter comes with Python, and the interface is the same on all three
    # systems.
    link = install_command(ctx, python)
    if SYSTEM == "Linux" and link is not None and not ctx.check_only:
        # The entry the autostart step already knows how to write, but in the
        # menu: starting at login is nobody's request, being found by typing
        # its name is.
        entry = applications_folder() / "greffier.desktop"
        make_folder(entry.parent)
        entry.write_text(LINUX_SHORTCUT.format(target=f"{link} fenetre"), encoding="utf-8")
        ok(f"« Greffier » dans le menu ({entry})")
    # Asked of the interpreter that was chosen, not of ours: the choice made at
    # step 5 may well carry a Tk the code cannot start, and a window that
    # refuses to open is then discovered at the first launch, once the
    # installation has declared itself finished. Seen: the smoothed text was
    # checked with « import tkinter » while the command itself would not
    # start.
    verdict = _the_window_can_open(python)
    if verdict is None:
        ok("interface disponible : « greffier fenetre »")
    elif verdict:
        ok(f"interface disponible : « greffier fenetre », {verdict}")
    else:
        warn("la fenêtre ne peut pas s'ouvrir avec cet interpréteur")
    if SYSTEM == "Linux":
        info("Si Tk manque : « apt install python3-tk ».")


# ------------------------------------------------------- 7b. the repair skill

def skills_folder():
    """Where Claude Code looks for the user's skills."""
    return Path.home() / ".claude/skills"


def skill_step(ctx):
    """Puts in place the skill that teaches Claude Code to repair an installation.

    Greffier depends on an authenticated Claude Code instance, it is the one
    writing the minutes, so it is the one turned to when something breaks.
    Without this document it gropes: it cannot guess that the data lives in
    Application Support and not in a hidden folder, that the bundle's
    signature has to stay stable, nor that the default model is the second
    of the range on purpose.

    A copy, not a link: the repository may be moved or deleted, and a skill
    pointing into the void would be worse than no skill.
    """
    title("7 bis. Dépannage assisté")
    if not shutil.which("claude"):
        info("Claude Code absent : les skills seront posés quand il le sera.")
        return

    # Every skill in the repository, not the repair one alone: they have
    # multiplied (assisting a meeting is a second), and an installer copying one
    # and forgetting the others is a trap for next time.
    sources = sorted(
        path for path in (ROOT / "skills").glob("*/SKILL.md") if path.exists()
    )
    if not sources:
        warn("aucun skill trouvé dans ce dépôt")
        return

    for source in sources:
        name = source.parent.name
        target = skills_folder() / name / "SKILL.md"
        if ctx.check_only:
            ok(f"skill « {name} » présent") if target.exists() else warn(
                f"skill « {name} » absent")
            continue
        if (target.exists()
                and target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")):
            ok(f"skill « {name} » à jour")
            continue
        action = "mis à jour" if target.exists() else "installé"
        if not ctx.ask(f"Installer le skill « {name} » pour Claude Code ?"):
            ctx.to_do.append(f"mkdir -p {target.parent} && cp {source} {target}")
            continue
        make_folder(target.parent)
        shutil.copy2(source, target)
        ok(f"skill « {name} » {action} ({target})")

    if not ctx.check_only:
        info("Dis « répare Greffier » ou « assiste ma réunion » à Claude Code.")


# ------------------------------------------------------------- 8. the check

def check_step(ctx, python):
    title("8. Vérification")
    if not python.exists():
        warn("environnement absent : vérification impossible")
        return False

    outcome = subprocess.run(
        [str(python), "-m", "pytest", str(ROOT / "tests")],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    resume = [
        line for line in outcome.stdout.splitlines()
        if "passed" in line or "failed" in line
    ]
    if outcome.returncode != 0:
        error(resume[-1] if resume else "les tests ont échoué")
        return False
    ok(resume[-1] if resume else "tests passés")

    voiceprints = ctx.models / "diarisation/nemo_en_titanet_large.onnx"
    if not voiceprints.exists():
        warn("modèle d'empreintes absent : identification des voix indisponible")
        return False
    controle = subprocess.run(
        [str(python), "-c",
         "import sys, pathlib;"
         "sys.path.insert(0, 'src');"
         "from greffier.adapters.voiceprints_titanet import TitaNetExtractor;"
         f"TitaNetExtractor(pathlib.Path(r'{voiceprints}'))"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    if controle.returncode != 0:
        error("le modèle d'empreintes ne se charge pas")
        info(controle.stderr.strip().splitlines()[-1] if controle.stderr.strip() else "")
        return False
    ok("modèle d'empreintes chargé")
    return True


# ---------------------------------------------------------------------- main

def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--oui", dest="yes", action="store_true",
                           help="installe sans poser de question")
    analyseur.add_argument("--verifier", dest="check", action="store_true",
                           help="constate l'état sans rien installer")
    analyseur.add_argument("--modeles", dest="models",
                           help="dossier où ranger les modèles")
    analyseur.add_argument("--config", help="dossier de configuration")
    args = analyseur.parse_args()

    print(_tint("1;37", f"Greffier : installation sur {SYSTEM} {platform.machine()}"))
    if sys.version_info < (3, 9):
        error(f"Python 3.9 minimum, trouvé {platform.python_version()}")
        return 1
    # Before computing any path at all: what lingers in the
    # hidden folders has to be moved, or the installer would find it there
    # again and keep writing to it.
    if not args.check:
        locations_step()
    ctx = Context(args)

    try:
        engine = system_tools_step(ctx)
        audio_step(ctx)
        models_step(ctx, engine)
        wording = writer_step(ctx)
        python = environment_step(ctx, engine)
        whisper_model_step(ctx, engine, python)
        configuration_step(ctx, engine, wording)
        desktop_step(ctx, python)
        skill_step(ctx)
        saine = check_step(ctx, python)
    except Abort as because:
        error(str(because))
        return 1
    except KeyboardInterrupt:
        error("interrompu")
        return 130

    if ctx.to_do:
        title("Reste à faire")
        for command in ctx.to_do:
            info(command)

    title("Installé." if saine else "Installé, avec des réserves.")
    info(f"modèles       {ctx.models}")

    # The installation lays the tools down; the assistant decides how they are
    # used. Chaining the two keeps a machine from staying installed but mute.
    if not ctx.check_only and python.exists():
        if ctx.yes or ctx.ask("Configurer maintenant (rédacteur, courriel, vocabulaire) ?"):
            greffier = greffier_command(python)
            if greffier.exists():
                subprocess.run([str(greffier), "configurer"], cwd=ROOT, check=False)
            else:
                info("Lance « greffier configurer » quand tu voudras.")
        else:
            info("À faire plus tard : greffier configurer")
    return 0 if saine else 1


if __name__ == "__main__":
    sys.exit(main())
