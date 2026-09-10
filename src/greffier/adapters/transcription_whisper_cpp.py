"""Transcription par whisper.cpp, accéléré Metal sur macOS.

Environ huit fois plus rapide que le temps réel sur un Mac Apple Silicon : une
réunion d'une heure est transcrite en quelques minutes.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from greffier.domain.models import Span, Utterance

_HORAIRE = re.compile(
    r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d\d\d)"
)

def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def lire_srt(path: Path) -> list[Utterance]:
    """Extrait les répliques d'un fichier de sous-titres."""
    utterances: list[Utterance] = []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return utterances
    for bloc in re.split(r"\n\s*\n", content):
        lines = [line for line in bloc.splitlines() if line.strip()]
        horaire = next(
            (_HORAIRE.search(line) for line in lines if _HORAIRE.search(line)), None
        )
        if not horaire:
            continue
        text = " ".join(
            line.strip() for line in lines
            if not _HORAIRE.search(line) and not line.strip().isdigit()
        )
        text = re.sub(r"^\(speaker \d+\)\s*", "", text).strip()
        if text:
            utterances.append(Utterance(
                span=Span(_seconds(*horaire.groups()[:4]),
                                      _seconds(*horaire.groups()[4:])),
                text=text,
            ))
    return utterances

class TranscripteurWhisperCpp:
    def __init__(self, model: Path, vad: Path | None = None, fils: int = 8) -> None:
        if not model.exists():
            raise FileNotFoundError(f"modèle de transcription introuvable : {model}")
        self.model = model
        self.vad = vad if vad and vad.exists() else None
        self.fils = fils

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / audio.stem
            command = [
                "whisper-cli", "-m", str(self.model), "-f", str(audio),
                "-l", language or "auto", "-t", str(self.fils), "-osrt", "-of", str(base),
            ]
            if self.vad:
                command += ["--vad", "--vad-model", str(self.vad)]
            if prompt_seed:
                command += ["--prompt", prompt_seed]
            outcome = subprocess.run(command, capture_output=True, text=True, check=False)
            srt = base.with_suffix(".srt")
            if outcome.returncode != 0 or not srt.exists():
                latest = (outcome.stderr or outcome.stdout).strip().splitlines()
                raise RuntimeError(
                    "whisper-cli a échoué" + (f" : {latest[-1]}" if latest else "")
                )
            return lire_srt(srt)
