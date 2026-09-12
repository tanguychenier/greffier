#!/usr/bin/env python3
"""Installe Greffier sur macOS, Linux ou Windows.

    python3 tools/install.py            # vérifie, propose, installe
    python3 tools/install.py --oui      # sans poser de question
    python3 tools/install.py --verifier # ne fait que constater

Écrit uniquement avec la bibliothèque standard : il doit tourner *avant* que
quoi que ce soit ne soit installé, donc il ne peut dépendre de rien. Compatible
Python 3.9, la version encore livrée par défaut sur beaucoup de postes.

Le script détecte ce qui manque et l'installe, plutôt que d'afficher une liste
de commandes à recopier. Chaque installation est annoncée et, sauf « --oui »,
demande confirmation : personne n'aime qu'un script touche à sa machine sans
prévenir.
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

# La console Windows par défaut est en cp1252 : elle ne sait écrire ni « ✓ » ni
# « é ». Sans ce basculement, l'installeur meurt sur un UnicodeEncodeError à sa
# toute première ligne — avant même d'avoir dit à quoi il sert.
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        with contextlib.suppress(OSError, ValueError):
            _flux.reconfigure(encoding="utf-8", errors="replace")


def _ecrivable(symbole):
    """Le symbole passe-t-il dans l'encodage de la console ?"""
    try:
        symbole.encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Repli en pur ASCII pour les consoles qui n'acceptent rien d'autre.
SYMBOLES = (
    {"ok": "✓", "alerte": "⚠", "erreur": "✗"}
    if _ecrivable("✓⚠✗")
    else {"ok": "[ok]", "alerte": "[!]", "erreur": "[X]"}
)

COLOURS = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _teinte(code, text):
    return f"\033[{code}m{text}\033[0m" if COLOURS else text


def title(text):
    print(_teinte("1;34", f"\n{text}"))


def ok(text):
    print(_teinte("0;32", f"  {SYMBOLES['ok']} {text}"))


def alerte(text):
    print(_teinte("0;33", f"  {SYMBOLES['alerte']} {text}"))


def erreur(text):
    print(_teinte("0;31", f"  {SYMBOLES['erreur']} {text}"), file=sys.stderr)


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


class Abandon(Exception):
    """Interrompt l'installation avec un message actionnable."""


# ----------------------------------------------------------------- décisions

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
        # Une chaîne d'origine peut déjà détenir les modèles : autant les
        # reprendre que retélécharger 1,6 Go. Vidable pour tester à blanc.
        reprise = os.environ.get("GREFFIER_MODELES_EXISTANTS", str(Path.home() / "reunions/models"))
        self.reprise = Path(reprise) if reprise else None
        self.to_do = []

    def ask(self, question):
        if self.check_only:
            return False
        if self.yes:
            return True
        if not sys.stdin.isatty():
            # Sans terminal (CI, script), ne rien installer en douce.
            alerte(f"{question} — passé (pas de terminal ; utilise --oui)")
            return False
        return input(f"    {question} [o/N] ").strip().lower() in {"o", "oui", "y", "yes"}


# Les emplacements sont ceux de l'application, lus dans son module sans
# dépendance — l'installeur tourne avant que le paquet ne soit installé, d'où le
# chargement par chemin. Une seule définition : l'installeur et Greffier ne
# peuvent pas se contredire sur l'endroit où sont les modèles.
def _charger_emplacements():
    specification = importlib.util.spec_from_file_location(
        "greffier_locations", ROOT / "src/greffier/locations.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


LOCATIONS = _charger_emplacements()


def data_folder():
    return LOCATIONS.data_folder(SYSTEM)


def config_folder():
    return LOCATIONS.config_folder(SYSTEM)


def etape_emplacements():
    """Sort de ~/.config et ~/.local ce qu'une version précédente y a laissé.

    macOS seulement : les dossiers cachés du compte y sont surveillés par les
    gardes du poste, qui redemandaient une autorisation à chaque accès, jusqu'à
    refuser une écriture en pleine réunion. Tout vit désormais dans Application
    Support. Ne fait rien ailleurs, ni quand il n'y a rien à bouger.
    """
    deplaces = LOCATIONS.relocate(SYSTEM)
    if not deplaces:
        return
    title("0. Emplacements")
    for source, target in deplaces:
        ok(f"{source} → {target}")


def run_job(command, **kwargs):
    """Exécute une commande en montrant ce qui est lancé."""
    info(f"$ {' '.join(command)}")
    return subprocess.run(command, check=False, **kwargs)


# ------------------------------------------------- gestionnaires de paquets

def carte_nvidia():
    """Si le poste a une carte NVIDIA que la transcription pourrait employer.

    macOS n'en a pas, et sa puce est déjà servie par Metal.
    """
    return SYSTEM != "Darwin" and shutil.which("nvidia-smi") is not None


def sound_server_present():
    """Si la session a un serveur de son auquel se brancher.

    « pactl » n'enregistre rien : il interroge le serveur, là où ffmpeg s'y
    branche directement par sa prise. Juger la capture sur cet outil déclarait
    donc perdue une machine parfaitement capable d'enregistrer — PipeWire en
    marche, mais « pulseaudio-utils » jamais installé.
    """
    if os.environ.get("PULSE_SERVER"):
        return True
    execution = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return (Path(execution) / "pulse" / "native").exists()


#: Les langues que Greffier propose, chargées depuis le paquet plutôt que
#: recopiées : trois copies d'une même liste, c'est trois occasions qu'elles se
#: contredisent. Chargement par chemin, comme les emplacements, parce que
#: l'installeur tourne avant que quoi que ce soit ne soit installé.
def _charger_catalogue():
    """Le catalogue des modèles, lu dans le paquet.

    Une seule liste : l'application le lit pour proposer les téléchargements
    manquants, l'installeur pour les poser. Deux copies auraient divergé au
    premier modèle changé.
    """
    nom = "greffier_model_files"
    specification = importlib.util.spec_from_file_location(
        nom, ROOT / "src/greffier/adapters/model_files.py"
    )
    module = importlib.util.module_from_spec(specification)
    # Inscrit avant exécution : un dataclass en `slots` va chercher son propre
    # module dans sys.modules pendant qu'il se construit, et échoue sinon.
    sys.modules[nom] = module
    specification.loader.exec_module(module)
    return module


def _charger_langues():
    specification = importlib.util.spec_from_file_location(
        "greffier_langues", ROOT / "src/greffier/domain/languages.py"
    )
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
    except Exception:
        # Le module importe le registre des profils, qui n'existe pas encore sur
        # un dépôt à moitié installé. Le repli est le français, comme avant.
        return None
    return module


def system_language():
    """La langue que le système annonce, si Greffier sait la servir.

    Renseignement gratuit que rien ne lisait : un poste allemand ressortait
    réglé sur le français, et personne ne s'en apercevait avant la première
    transcription.
    """
    languages = _charger_langues()
    known = {code for code, _ in languages.LANGUAGES} if languages else {"fr"}
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "")
        if value:
            code = value.split(".")[0].split("_")[0].lower()
            if code in known:
                return code
    return "fr"


def gestionnaire():
    """Le gestionnaire de paquets du poste, ou None si aucun n'est reconnu."""
    if SYSTEM == "Darwin":
        return ("brew", ["brew", "install"]) if shutil.which("brew") else None
    if SYSTEM == "Windows":
        if shutil.which("winget"):
            return ("winget", ["winget", "install", "--accept-package-agreements",
                               "--accept-source-agreements", "-e", "--id"])
        if shutil.which("scoop"):
            return ("scoop", ["scoop", "install"])
        return None
    # En conteneur ou en intégration continue on tourne en root, où « sudo »
    # n'est souvent même pas installé.
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


# Nom du paquet selon le gestionnaire : ffmpeg s'appelle pareil partout, mais
# ce n'est pas le cas de tout.
PAQUETS = {
    "ffmpeg": {
        "brew": "ffmpeg", "apt-get": "ffmpeg", "dnf": "ffmpeg", "pacman": "ffmpeg",
        "zypper": "ffmpeg", "apk": "ffmpeg",
        "winget": "Gyan.FFmpeg", "scoop": "ffmpeg",
    },
    "whisper-cpp": {
        # Empaqueté seulement par Homebrew. Ailleurs, la transcription passe
        # par faster-whisper, installé dans l'environnement Python.
        "brew": "whisper-cpp",
    },
    "ollama": {
        "brew": "ollama", "winget": "Ollama.Ollama", "scoop": "ollama",
    },
    "uv": {
        "brew": "uv", "winget": "astral-sh.uv", "scoop": "uv",
    },
}


def installer_paquet(ctx, name, because):
    gest = gestionnaire()
    if gest is None:
        alerte(f"{name} absent, et aucun gestionnaire de paquets reconnu sur ce poste")
        info(f"Installe-le à la main : {because}")
        return False
    outil, command = gest
    package = PAQUETS.get(name, {}).get(outil)
    if package is None:
        alerte(f"{name} n'est pas empaqueté par {outil}")
        return False
    if not ctx.ask(f"Installer {name} avec {outil} ? ({because})"):
        ctx.to_do.append(f"{' '.join(command)} {package}")
        return False
    if outil == "apt-get":
        # Sans rafraîchissement, apt échoue sur une image ou un poste dont la
        # liste de paquets n'a jamais été mise à jour.
        run_job(command[:-2] + ["update", "-qq"], stdout=subprocess.DEVNULL)
    return run_job(command + [package]).returncode == 0


# ---------------------------------------------------------- 1. outils système

def system_tools_step(ctx):
    title("1. Outils système")

    if shutil.which("ffmpeg"):
        ok("ffmpeg")
    elif not installer_paquet(ctx, "ffmpeg", "enregistrement et conversion audio"):
        raise Abandon("ffmpeg est indispensable : sans lui, rien ne peut être enregistré.")

    # whisper.cpp accélère la transcription sur le processeur graphique, mais
    # n'existe en paquet que sur macOS. Son absence n'est pas bloquante :
    # faster-whisper prend le relais, en Python, sur les trois systèmes.
    if shutil.which("whisper-cli") or shutil.which("whisper"):
        ok("whisper.cpp (transcription accélérée)")
        return "whisper.cpp"
    if SYSTEM == "Darwin" and installer_paquet(
        ctx, "whisper-cpp", "transcription accélérée Metal"
    ):
        ok("whisper.cpp")
        return "whisper.cpp"
    alerte("whisper.cpp absent — la transcription passera par faster-whisper (Python)")
    return "faster-whisper"


# ---------------------------------------------------------- 2. capture audio

def etape_audio(ctx):
    """Vérifie de quoi capter le son des autres participants.

    C'est le seul point vraiment différent d'un système à l'autre : entendre sa
    propre voix est trivial, réenregistrer ce que les haut-parleurs jouent ne
    l'est pas.
    """
    title("2. Capture du son des autres participants")

    if SYSTEM == "Darwin":
        output = subprocess.run(
            ["system_profiler", "SPAudioDataType"], capture_output=True, text=True, check=False
        ).stdout
        if "BlackHole" in output:
            ok("BlackHole (pilote audio virtuel)")
        else:
            alerte("BlackHole absent : sans lui, seule ta voix serait enregistrée")
            if ctx.ask("Installer BlackHole ? (mot de passe admin demandé)"):
                run_job(["brew", "install", "--cask", "blackhole-2ch"])
                info("Puis : sudo killall coreaudiod   (recharge le son, coupure de 1-2 s)")
            else:
                ctx.to_do.append("brew install --cask blackhole-2ch")
                ctx.to_do.append("sudo killall coreaudiod")
        return

    if SYSTEM == "Linux":
        # PipeWire et PulseAudio exposent déjà un « monitor » de la sortie :
        # rien à installer, contrairement à macOS.
        if sound_server_present():
            ok("PulseAudio/PipeWire — le moniteur de sortie sert de capture")
            info("Aucun pilote supplémentaire n'est nécessaire sur Linux.")
        else:
            alerte("aucun serveur de son : le son des autres participants ne pourra pas"
                   " être capté")
            info("Sur un poste de bureau, installe « pipewire-pulse » ou « pulseaudio ».")
            info("En conteneur ou sur un serveur, c'est normal : seule l'analyse de")
            info("fichiers déjà enregistrés est possible.")
        return

    ok("WASAPI (capture de boucle intégrée à Windows)")
    info("ffmpeg capte la sortie via « -f dshow » ou la boucle WASAPI.")


# ---------------------------------------------------------------- 3. modèles

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
        # Le modèle du direct. Il transcrit une tranche de dix secondes en une
        # fraction de seconde là où le grand en prend plusieurs : pendant la
        # réunion, il faut rendre une tranche avant que la suivante soit
        # enregistrée, sinon l'affichage prend un retard qu'il ne rattrape plus.
        # Facultatif — sans lui, le direct se replie sur le grand modèle.
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

# La voix de l'assistant, quand il participe à la réunion. Un VITS français,
# tenu par le sherpa-onnx déjà installé pour la segmentation : aucune dépendance
# nouvelle, aucun appel réseau.
#
# Retenu à l'écoute contre trois autres, dont Kokoro multilingue qui servait
# jusqu'ici. Il gagne sur les deux tableaux : plus naturel, et **quarante-huit
# fois le temps réel** contre cinq — quatre secondes de parole calculées en
# huit centièmes, là où l'autre en prenait presque une seconde. Quatre-vingts
# mégaoctets contre trois cent vingt-cinq.
#
# Facultatif. Sans lui, l'assistant se replie sur la voix du système, qui est
# livrée partout et s'entend tout de suite : c'est jouable, mais on ne montre
# pas cela à quelqu'un. C'est donc le seul modèle qu'on télécharge pour une
# question de qualité perçue, et il est le premier qu'on retire d'une
# installation à l'étroit.
VOICE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "tts-models/vits-piper-fr_FR-upmc-medium.tar.bz2"
)

#: Le dossier que l'archive dépose, à renommer en « voix ».
VOIX_DOSSIER = "vits-piper-fr_FR-upmc-medium"

#: Ce qu'une archive de voix peut contenir sans servir au français : les
#: lexiques et grammaires d'autres langues, que le modèle multilingue traînait.
#: Absents d'un modèle français, d'où la suppression tolérante.
VOIX_INUTILES = ("lexicon-gb-en.txt", "lexicon-us-en.txt", "lexicon-zh.txt",
                 "date-zh.fst", "number-zh.fst", "phone-zh.fst")


def relier_ou_copier(source, target, folder=False):
    """Relie la source à la cible, ou la copie si le système s'y refuse.

    Windows n'autorise les liens symboliques qu'en mode développeur ou en
    session élevée. Copier coûte de l'espace, mais un modèle de 98 Mo dupliqué
    vaut mieux qu'une installation qui échoue.
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
    """Télécharge en affichant la progression, sans laisser de fichier tronqué."""
    partiel = target.with_suffix(target.suffix + ".partiel")
    with urllib.request.urlopen(url) as stream, open(partiel, "wb") as output:
        total = int(stream.headers.get("Content-Length") or 0)
        recu = 0
        while True:
            morceau = stream.read(1 << 20)
            if not morceau:
                break
            output.write(morceau)
            recu += len(morceau)
            if total and sys.stdout.isatty():
                print(f"\r    {target.name} {recu * 100 // total:3d} %", end="", flush=True)
    if sys.stdout.isatty():
        print("\r", end="")
    # Renommage seulement une fois complet : une coupure de réseau ne doit pas
    # laisser un modèle tronqué qui échouerait bien plus tard, à l'exécution.
    partiel.replace(target)


def etape_modeles(ctx, engine):
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
            comment = relier_ou_copier(former, target)
            ok(f"{target.name} {comment} {former}")
            continue
        if ctx.check_only:
            alerte(f"{target.name} manquant ({model['role']})")
            continue
        info(f"téléchargement de {target.name} ({model['role']})…")
        download(model["url"], target)
        ok(target.name)

    _installer_la_segmentation(ctx)
    _installer_la_voix(ctx)


def _installer_la_segmentation(ctx):
    """Le modèle qui repère quand quelqu'un parle. Requis, lui."""
    folder = ctx.models / "diarisation/sherpa-onnx-pyannote-segmentation-3-0"
    if (folder / "model.onnx").exists():
        ok("modèle de segmentation")
        return
    former = (
        ctx.reprise / "diarisation/sherpa-onnx-pyannote-segmentation-3-0"
        if ctx.reprise else None
    )
    if former and (former / "model.onnx").exists():
        comment = relier_ou_copier(former, folder, folder=True)
        ok(f"modèle de segmentation {comment} {former}")
        return
    if ctx.check_only:
        alerte("modèle de segmentation manquant")
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


def voix_presente(folder):
    """Un réseau et son vocabulaire, quel que soit le nom du fichier.

    Chercher « model.onnx » ne valait que pour Kokoro : un VITS nomme ses poids
    d'après sa voix (« fr_FR-upmc-medium.onnx »). L'installation annonçait donc
    la voix manquante alors qu'elle était en place, et proposait de la
    retélécharger à chaque passage. Même critère que l'adaptateur, pour que les
    deux ne puissent pas se contredire.
    """
    return any(folder.glob("*.onnx")) and (folder / "tokens.txt").exists()


def _installer_la_voix(ctx):
    """La voix de l'assistant. Facultative : son absence n'arrête rien.

    Un échec ici ne doit pas faire échouer une installation par ailleurs
    complète : l'outil enregistre, transcrit et rédige sans jamais ouvrir la
    bouche, et c'est même son mode par défaut.
    """
    folder = ctx.models / "voix"
    if voix_presente(folder):
        ok("voix de l'assistant")
        return
    if ctx.check_only:
        alerte("voix de l'assistant manquante (il se repliera sur celle du système)")
        return
    archive = ctx.models / "voix.tar.bz2"
    info("téléchargement de la voix de l'assistant (80 Mo)…")
    try:
        download(VOICE, archive)
        with tarfile.open(archive, "r:bz2") as package:
            if sys.version_info >= (3, 12):
                package.extractall(ctx.models, filter="data")
            else:
                package.extractall(ctx.models)  # noqa: S202
        extrait = ctx.models / VOIX_DOSSIER
        if extrait.exists():
            if folder.exists():
                shutil.rmtree(folder)
            extrait.rename(folder)
        for inutile in VOIX_INUTILES:
            (folder / inutile).unlink(missing_ok=True)
        ok("voix de l'assistant")
    except (OSError, tarfile.TarError) as trouble:
        alerte(f"voix de l'assistant non installée ({trouble}) : "
               "l'assistant parlera avec la voix du système.")
    finally:
        archive.unlink(missing_ok=True)


# ------------------------------------------------------- 4. rédaction du CR

# Modèles locaux acceptés, par ordre de préférence : on réutilise ce qui est
# déjà sur le poste avant de proposer un téléchargement de plusieurs gigaoctets.
# Le critère est la qualité de synthèse en français à taille raisonnable.
FAMILLES_OLLAMA = ("qwen3", "mistral-small", "gemma3", "llama3.1", "qwen2.5")
OLLAMA_MODEL = os.environ.get("GREFFIER_MODELE_OLLAMA", "qwen3:8b")


def modele_utilisable(disponibles):
    """Premier modèle présent appartenant à une famille reconnue.

    La comparaison porte sur le début du nom : « qwen3.8 », « qwen3:8b » et
    « qwen3:14b » sont la même famille, et l'un ou l'autre fera l'affaire.
    """
    for famille in FAMILLES_OLLAMA:
        for present in disponibles:
            if present.split(":")[0].replace(".", "").startswith(famille.replace(".", "")):
                return present
    return None


def modeles_ollama():
    try:
        output = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=False, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split()[0] for line in output.splitlines()[1:] if line.strip()]


def etape_redaction(ctx):
    """Choisit qui rédige le compte rendu.

    Claude Code par défaut : distinguer une décision d'une hypothèse et
    rattacher une position à une personne reste hors de portée des modèles qui
    tournent sur un portable. C'est le seul maillon de la chaîne qui sort du
    poste, et c'est un choix assumé.

    Ollama reste branchable pour qui veut du 100 % local — l'architecture le
    permet sans rien changer d'autre — au prix d'une synthèse plus grossière.
    """
    title("4. Rédaction du compte rendu")

    if shutil.which("claude"):
        ok("Claude Code — rédacteur par défaut")
        info("La transcription sort du poste vers l'API Anthropic ; le reste de la")
        info("chaîne demeure local. Pour ne rien laisser sortir : moteur « ollama ».")
        return {"moteur": "claude", "modele": ""}

    alerte("Claude Code absent : c'est le rédacteur par défaut")
    info("Installation : https://claude.com/claude-code")

    if shutil.which("ollama"):
        disponibles = modeles_ollama()
        found = modele_utilisable(disponibles)
        if found:
            ok(f"Ollama disponible en remplacement : {found} (tout reste local)")
            return {"moteur": "ollama", "modele": found}
        alerte(
            f"Ollama installé mais aucun modèle de synthèse reconnu "
            f"({len(disponibles)} présents)"
        )
        if ctx.ask(
            f"Télécharger {OLLAMA_MODEL} pour rédiger en local ? (~5 Go)"
        ) and run_job(["ollama", "pull", OLLAMA_MODEL]).returncode == 0:
            return {"moteur": "ollama", "modele": OLLAMA_MODEL}
        ctx.to_do.append(f"ollama pull {OLLAMA_MODEL}")

    alerte("aucun rédacteur : transcription et voix fonctionneront, pas le compte rendu")
    return {"moteur": "aucun", "modele": ""}


MODELE_WHISPER = os.environ.get("GREFFIER_MODELE_WHISPER", "large-v3")


def etape_modele_whisper(ctx, engine, python):
    """Récupère le modèle de faster-whisper, là où whisper.cpp n'existe pas.

    Sans cette étape, tout paraît installé et le téléchargement de 1,5 Go se
    déclenche au lancement de la première réunion — c'est-à-dire au pire moment.
    """
    if engine != "faster-whisper" or ctx.check_only or not python.exists():
        return
    title("5 bis. Modèle de transcription (faster-whisper)")
    info(f"préparation de « {MODELE_WHISPER} »…")
    outcome = subprocess.run(
        [str(python), "-c",
         "from faster_whisper import WhisperModel;"
         f"WhisperModel('{MODELE_WHISPER}', device='cpu', compute_type='int8')"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    if outcome.returncode == 0:
        ok(f"modèle {MODELE_WHISPER} prêt")
    else:
        alerte(f"modèle {MODELE_WHISPER} non préparé : il sera récupéré au premier usage")
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
    demande = (
        "import tkinter;"
        "r = tkinter.Tk(); r.withdraw();"
        "print(r.tk.eval('tk::pkgconfig get fontsystem'))"
    )
    try:
        lu = subprocess.run(
            [interpreter, "-c", demande],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if lu.returncode != 0:
        return None
    return lu.stdout.strip().endswith("xft")


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
    for nom in ("python3.13", "python3.14", "python3.15"):
        chemin = shutil.which(nom)
        if chemin is None:
            continue
        verdict = antialiases(chemin)
        if verdict is False:
            continue
        # None means it could not be asked -- no display. A distribution's Tk
        # is built with Xft as a rule, so it is still the better bet.
        if verdict or _has_tkinter(chemin):
            return chemin
    return None


def _has_tkinter(interpreter: str) -> bool:
    lu = subprocess.run(
        [interpreter, "-c", "import tkinter"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    return lu.returncode == 0


def etape_environnement(ctx, engine):
    title("5. Environnement Python")
    venv = ROOT / ".venv"
    python = venv / ("Scripts/python.exe" if SYSTEM == "Windows" else "bin/python")

    extras = "dev" + (",transcription" if engine == "faster-whisper" else "")
    if engine == "faster-whisper" and carte_nvidia():
        # La carte seule ne suffit pas : CTranslate2 réclame cuBLAS et cuDNN,
        # qu'aucune distribution ne livre avec le pilote. Sans elles la
        # transcription tombe sur le processeur, treize fois plus lent —
        # treize heures pour une réunion d'une heure.
        if ctx.ask("Installer l'accélération CUDA ? (2,2 Go, la transcription"
                        " passe de treize fois le temps réel à un tiers)"):
            extras += ",cuda"
        else:
            ctx.to_do.append("uv pip install -e '.[cuda]'")

    if ctx.check_only:
        ok("environnement présent") if python.exists() else alerte("environnement absent")
        return python

    if SYSTEM == "Darwin" and not shutil.which("uv"):
        # L'application embarque un interpréteur relogeable : seul uv en
        # installe un (python-build-standalone), et seul uv sait le remplir.
        # Sans lui, la ligne de commande fonctionne mais pas le paquet .app.
        installer_paquet(ctx, "uv", "interpréteur relogeable, embarqué dans l'application")

    # Le contrôle porte sur l'**interpréteur**, jamais sur le dossier. Un
    # « .venv » venu d'une autre machine — un dossier de projet copié, une
    # sauvegarde restaurée, une image construite depuis un dépôt de travail —
    # existe sans que son interpréteur existe : les liens qu'il contient
    # pointent vers un chemin d'ailleurs. L'installation annonçait alors
    # « repli sur venv + pip », sautait la création, et tombait sur
    # « No such file or directory: .venv/bin/python ». Mesuré : c'est ce qui
    # arrêtait net l'installation sous Linux.
    if venv.exists() and not python.exists():
        alerte("environnement Python inutilisable (venu d'une autre machine ?), "
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
                    alerte("texte non lissé dans la fenêtre : aucun Python 3.13 "
                           "du système n'a été trouvé")
                    info("« apt install python3.13-tk » (dépôt deadsnakes) le corrige, "
                         "puis relance cette installation.")
                run_job(["uv", "venv", "--python", "3.13"], cwd=ROOT)
        run_job(["uv", "pip", "install", "-q", "-e", f".[{extras}]"], cwd=ROOT)
    else:
        alerte("uv absent — repli sur venv + pip, plus lent")
        if not python.exists():
            run_job([sys.executable, "-m", "venv", str(venv)])
        if not python.exists():
            # S'arrêter ici et le dire : la suite échouerait de toute façon,
            # trois lignes plus bas, sur une trace Python que personne ne relie
            # au paquet manquant.
            erreur("l'environnement Python n'a pas pu être créé. Sous Debian et "
                   "Ubuntu, « apt install python3-venv » le fournit.")
            raise SystemExit(1)
        run_job([str(python), "-m", "pip", "install", "-q", "-e", f".[{extras}]"], cwd=ROOT)
    ok(f"dépendances installées ({extras})")
    return python


# -------------------------------------------------------- 6. configuration

GABARIT = '''# Configuration de Greffier. Tout est facultatif : ce qui manque reprend la
# valeur par défaut.

[chemins]
modeles = {modeles!r}
donnees = {donnees!r}

[audio]
# Périphériques de capture. Sur macOS, à créer une fois (voir le README) ;
# sur Linux, le moniteur de sortie PipeWire/PulseAudio suffit.
entree = {entree!r}
sortie = {sortie!r}
duree_maximale = 14400        # 4 h : garde-fou contre une réunion oubliée

[transcription]
moteur = {moteur!r}           # whisper.cpp (macOS, accéléré) ou faster-whisper
langue = {langue!r}
# Noms propres du contexte : c'est ce qui améliore le plus la transcription
# des termes rares.
vocabulaire = ["Jira", "GitLab", "sprint", "merge request", "recette", "backlog"]

[locuteurs]
# Mots à ne jamais prendre pour des prénoms : projets, outils, produits.
pas_des_prenoms = ["Copernic", "Kanban", "Trello"]

[compte_rendu]
# claude : meilleure synthèse, la transcription sort vers l'API Anthropic.
# ollama : tout reste sur le poste, synthèse plus grossière.
moteur = {redacteur!r}
modele = {modele!r}
# Adresse à qui envoyer le compte rendu. Vide = pas d'envoi.
destinataire = ""
'''


def etape_configuration(ctx, engine, wording):
    title("6. Configuration")
    make_folder(ctx.config)
    file = ctx.config / "config.toml"
    if file.exists():
        ok(f"configuration existante conservée : {file}")
        return file
    if ctx.check_only:
        alerte(f"configuration absente : {file}")
        return file
    file.write_text(
        GABARIT.format(
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
    alerte("renseigne « destinataire » pour recevoir les comptes rendus par mail")
    return file


# ------------------------------------------------------ 7. intégration bureau

def dossier_autodemarrage():
    """Où déposer ce qui doit se lancer à l'ouverture de session."""
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

RACCOURCI_LINUX = """[Desktop Entry]
Type=Application
Name=Greffier
Comment=Enregistre la réunion et en rédige le compte rendu
Exec={target}
Terminal=false
Categories=Office;AudioVideo;
"""

# Un .cmd plutôt qu'un .lnk : un raccourci Windows est un format binaire qui
# demande PowerShell et COM pour être écrit, là où un script démarre aussi bien
# et reste lisible par qui veut savoir ce qui se lance à sa session.
DEMARRAGE_WINDOWS = """@echo off
rem Lance Greffier à l'ouverture de session. Supprime ce fichier pour l'annuler.
start "" /min {target}
"""


def integrer_au_bureau(ctx, target, write=True):
    """Pose l'icône dans la barre et le lancement à l'ouverture de session.

    Renvoie le fichier écrit, ou None si le système n'est pas reconnu. La
    séparation « ecrire » permet de vérifier ce qui serait produit sur les trois
    systèmes depuis n'importe quel poste.
    """
    folder = dossier_autodemarrage()
    if SYSTEM == "Darwin":
        file, gabarit = folder / "com.reunions.greffier.plist", AGENT_MACOS
    elif SYSTEM == "Windows":
        file, gabarit = folder / "Greffier.cmd", DEMARRAGE_WINDOWS
    elif SYSTEM == "Linux":
        file, gabarit = folder / "greffier.desktop", RACCOURCI_LINUX
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
        ok(f"commande « greffier » disponible ({link})") if already_there else alerte(
            "commande « greffier » absente du PATH")
        return link if already_there else None
    if already_there:
        ok(f"commande « greffier » disponible ({link})")
    elif not launcher.exists():
        alerte("lanceur introuvable dans l'environnement Python")
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


def etape_bureau(ctx, python):
    """Installe l'interface : la commande dans le PATH, l'entrée dans le menu."""
    title("7. Intégration au bureau")

    if SYSTEM == "Darwin":
        if not (ROOT / "macos/construire.sh").exists():
            alerte("script de construction introuvable dans ce dépôt")
            return
        # /Applications d'abord : ~/Applications n'est indexé ni par Spotlight ni
        # par le Launchpad, donc une application qui y est posée n'y apparaît
        # jamais. Constaté en usage : « je n'ai aucune icône pour la lancer ».
        candidates = [Path("/Applications/Greffier.app"),
                      Path.home() / "Applications/Greffier.app"]
        application = next((c for c in candidates if c.exists()), candidates[0])
        if ctx.check_only:
            ok(f"application présente ({application})") if application.exists() \
                else alerte("application absente")
            return
        # Autonome et signée de façon stable (voir macos/construire.sh) : les
        # autorisations micro et Outlook, données une fois, ne sont plus
        # redemandées à la reconstruction suivante.
        if run_job([str(ROOT / "macos/construire.sh")]).returncode != 0:
            alerte("construction de l'application échouée")
            return
        pose = next((c for c in candidates if c.exists()), None)
        ok(f"application installée ({pose or application})")
        info("Double-clic, ou cherche « Greffier » dans le Launchpad.")
        return

    # Ailleurs, la fenêtre se lance par la ligne de commande. Rien à compiler :
    # Tkinter vient avec Python, et l'interface est la même sur les trois
    # systèmes.
    link = install_command(ctx, python)
    if SYSTEM == "Linux" and link is not None and not ctx.check_only:
        # The entry the autostart step already knows how to write, but in the
        # menu: starting at login is nobody's request, being found by typing
        # its name is.
        entry = applications_folder() / "greffier.desktop"
        make_folder(entry.parent)
        entry.write_text(RACCOURCI_LINUX.format(target=f"{link} fenetre"), encoding="utf-8")
        ok(f"« Greffier » dans le menu ({entry})")
    ok("interface disponible : « greffier fenetre »")
    if SYSTEM == "Linux":
        info("Si Tk manque : « apt install python3-tk ».")


# --------------------------------------------------- 7 bis. skill de dépannage

def dossier_skills():
    """Où Claude Code cherche les skills de l'utilisateur."""
    return Path.home() / ".claude/skills"


def etape_skill(ctx):
    """Pose le skill qui apprend à Claude Code à réparer une installation.

    Greffier dépend d'une instance Claude Code authentifiée — c'est elle qui
    rédige le compte rendu — donc c'est vers elle qu'on se tourne quand quelque
    chose casse. Sans ce document, elle tâtonne : elle ne peut pas devenir que
    les données vivent dans Application Support et non dans un dossier caché,
    que la signature du paquet doit rester stable, ni que le modèle par défaut
    est le second de la gamme à dessein.

    Une copie, pas un lien : le dépôt peut être déplacé ou supprimé, un skill
    qui pointerait dans le vide serait pire que pas de skill.
    """
    title("7 bis. Dépannage assisté")
    if not shutil.which("claude"):
        info("Claude Code absent : les skills seront posés quand il le sera.")
        return

    # Tous les skills du dépôt, et non le seul dépannage : ils se sont
    # multipliés (assister une réunion en est un second), et un installeur qui
    # en copie un et oublie les autres est un piège pour la fois suivante.
    sources = sorted(
        path for path in (ROOT / "skills").glob("*/SKILL.md") if path.exists()
    )
    if not sources:
        alerte("aucun skill trouvé dans ce dépôt")
        return

    for source in sources:
        name = source.parent.name
        target = dossier_skills() / name / "SKILL.md"
        if ctx.check_only:
            ok(f"skill « {name} » présent") if target.exists() else alerte(
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


# ---------------------------------------------------------- 8. vérification

def etape_verification(ctx, python):
    title("8. Vérification")
    if not python.exists():
        alerte("environnement absent : vérification impossible")
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
        erreur(resume[-1] if resume else "les tests ont échoué")
        return False
    ok(resume[-1] if resume else "tests passés")

    voiceprints = ctx.models / "diarisation/nemo_en_titanet_large.onnx"
    if not voiceprints.exists():
        alerte("modèle d'empreintes absent : identification des voix indisponible")
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
        erreur("le modèle d'empreintes ne se charge pas")
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

    print(_teinte("1;37", f"Greffier — installation sur {SYSTEM} {platform.machine()}"))
    if sys.version_info < (3, 9):
        erreur(f"Python 3.9 minimum, trouvé {platform.python_version()}")
        return 1
    # Avant de calculer le moindre chemin : ce qui traîne dans les dossiers
    # cachés doit être rangé, sinon l'installeur le retrouverait là-bas et
    # continuerait d'y écrire.
    if not args.check:
        etape_emplacements()
    ctx = Context(args)

    try:
        engine = system_tools_step(ctx)
        etape_audio(ctx)
        etape_modeles(ctx, engine)
        wording = etape_redaction(ctx)
        python = etape_environnement(ctx, engine)
        etape_modele_whisper(ctx, engine, python)
        etape_configuration(ctx, engine, wording)
        etape_bureau(ctx, python)
        etape_skill(ctx)
        saine = etape_verification(ctx, python)
    except Abandon as because:
        erreur(str(because))
        return 1
    except KeyboardInterrupt:
        erreur("interrompu")
        return 130

    if ctx.to_do:
        title("Reste à faire")
        for command in ctx.to_do:
            info(command)

    title("Installé." if saine else "Installé, avec des réserves.")
    info(f"modèles       {ctx.models}")

    # L'installation pose les outils ; l'assistant décide de comment on s'en
    # sert. Enchaîner les deux évite qu'un poste reste installé mais muet.
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
