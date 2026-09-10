"""The models the tool needs, and how to fetch them.

They live outside the application, in the data folder, and that is deliberate:
an update swaps the bundle and the 1.7 GB stays where it is. It also means a
freshly downloaded application has none of them, and until now only the
command-line installer knew how to fetch them — so double-clicking the
published archive gave a tool that could not transcribe anything.

The catalogue lives here rather than in the installer so that both read the
same list. The installer loads this module by path, before pydantic exists.
"""

from __future__ import annotations

import contextlib
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

TELECHARGEMENT = 1800.0
"""Seconds allowed for one model. A 1.5 GB file on a slow line takes a while."""

MORCEAU = 1 << 20
"""Read size. A megabyte keeps the progress smooth without thrashing."""


@dataclass(frozen=True, slots=True)
class Model:
    """One model: where it goes, where it comes from, and what it is for."""

    name: str
    url: str
    minimum: int
    role: str
    engine: str = ""
    archive: bool = False
    folder: str = ""
    required: bool = True

    def target(self, folder: Path) -> Path:
        return folder / self.name

    def present(self, folder: Path) -> bool:
        """True when the file is there **and** big enough to be whole.

        Size matters: a download cut halfway leaves a file that exists and
        fails much later, at transcription time.
        """
        cible = self.target(folder)
        if self.archive:
            return cible.is_dir() and any(cible.iterdir())
        return cible.exists() and cible.stat().st_size >= self.minimum


CATALOGUE: tuple[Model, ...] = (
    Model(
        name="ggml-large-v3-turbo.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
            "ggml-large-v3-turbo.bin",
        minimum=1_000_000_000,
        role="transcription",
        engine="whisper.cpp",
    ),
    Model(
        name="ggml-silero-v5.1.2.bin",
        url="https://huggingface.co/ggml-org/whisper-vad/resolve/main/"
            "ggml-silero-v5.1.2.bin",
        minimum=500_000,
        role="détection de la parole",
        engine="whisper.cpp",
    ),
    Model(
        name="ggml-small.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
            "ggml-small.bin",
        minimum=400_000_000,
        role="transcription en direct",
        engine="whisper.cpp",
        required=False,
    ),
    Model(
        name="diarisation/nemo_en_titanet_large.onnx",
        url="https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            "speaker-recongition-models/nemo_en_titanet_large.onnx",
        minimum=20_000_000,
        role="empreintes vocales",
    ),
    Model(
        name="diarisation/sherpa-onnx-pyannote-segmentation-3-0",
        url="https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            "speaker-segmentation-models/"
            "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
        minimum=1_000_000,
        role="découpage en tours de parole",
        archive=True,
    ),
    Model(
        name="voix",
        url="https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            "tts-models/vits-piper-fr_FR-upmc-medium.tar.bz2",
        minimum=50_000_000,
        role="voix de l'assistant",
        archive=True,
        folder="vits-piper-fr_FR-upmc-medium",
        required=False,
    ),
)


def missing(folder: Path, engine: str = "whisper.cpp") -> list[Model]:
    """The models this machine still needs, heaviest first."""
    manquants = [
        m for m in CATALOGUE
        if (not m.engine or m.engine == engine) and not m.present(folder)
    ]
    return sorted(manquants, key=lambda m: -m.minimum)


def weight(models: list[Model]) -> str:
    """What the download will cost, in words a person reads."""
    octets = sum(m.minimum for m in models)
    if octets >= 1_000_000_000:
        return f"{octets / 1_000_000_000:.1f} Go"
    return f"{octets / 1_000_000:.0f} Mo"


def fetch(
    model: Model, folder: Path, progress: Callable[[int, int], None] | None = None,
    delai: float = TELECHARGEMENT,
) -> tuple[bool, str]:
    """Fetches one model into the folder. Never raises.

    Written to a `.partiel` file and renamed only once whole: a network cut
    must not leave a truncated model that fails much later, at transcription
    time.
    """
    cible = model.target(folder)
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_suffix(cible.suffix + ".partiel")
    requete = urllib.request.Request(model.url, headers={"User-Agent": "Greffier"})
    try:
        with urllib.request.urlopen(requete, timeout=delai) as flux:
            total = int(flux.headers.get("Content-Length") or 0)
            recu = 0
            with partiel.open("wb") as sortie:
                while morceau := flux.read(MORCEAU):
                    sortie.write(morceau)
                    recu += len(morceau)
                    if progress is not None:
                        progress(recu, total)
    except (urllib.error.URLError, TimeoutError):
        partiel.unlink(missing_ok=True)
        return (False, "pas de réseau")
    except OSError as souci:
        partiel.unlink(missing_ok=True)
        return (False, str(souci))

    if not model.archive:
        partiel.replace(cible)
        return (True, str(cible))
    resultat = _deballer(partiel, model, folder)
    partiel.unlink(missing_ok=True)
    return resultat


def _deballer(archive: Path, model: Model, folder: Path) -> tuple[bool, str]:
    """Opens an archive and puts its folder where the tool expects it."""
    atelier = folder / f".{model.target(folder).name}.atelier"
    with contextlib.suppress(OSError):
        if atelier.exists():
            _effacer(atelier)
    try:
        atelier.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as boite:
            boite.extractall(atelier, filter="data")
    except (OSError, tarfile.TarError) as souci:
        _effacer(atelier)
        return (False, str(souci))

    dedans = [p for p in atelier.iterdir() if p.is_dir()]
    venu = next((p for p in dedans if p.name == model.folder), None) or (
        dedans[0] if dedans else None
    )
    if venu is None:
        _effacer(atelier)
        return (False, "archive vide")
    cible = model.target(folder)
    with contextlib.suppress(OSError):
        if cible.exists():
            _effacer(cible)
    try:
        venu.replace(cible)
    except OSError as souci:
        _effacer(atelier)
        return (False, str(souci))
    _effacer(atelier)
    return (True, str(cible))


def _effacer(chemin: Path) -> None:
    import shutil

    with contextlib.suppress(OSError):
        if chemin.is_dir():
            shutil.rmtree(chemin)
        else:
            chemin.unlink(missing_ok=True)
