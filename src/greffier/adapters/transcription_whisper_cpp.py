"""Transcription through whisper.cpp, Metal-accelerated on macOS."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from greffier.domain.arithmetic import AUTO
from greffier.domain.models import Span, Utterance
from greffier.domain.transcription import without_loop

_TIMING = re.compile(
    r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d\d\d)"
)

def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def lire_srt(path: Path) -> list[Utterance]:
    """Extracts the utterances from a subtitle file."""
    utterances: list[Utterance] = []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return utterances
    for block in re.split(r"\n\s*\n", content):
        lines = [line for line in block.splitlines() if line.strip()]
        timing = next(
            (_TIMING.search(line) for line in lines if _TIMING.search(line)), None
        )
        if not timing:
            continue
        text = " ".join(
            line.strip() for line in lines
            if not _TIMING.search(line) and not line.strip().isdigit()
        )
        text = re.sub(r"^\(speaker \d+\)\s*", "", text).strip()
        if text:
            utterances.append(Utterance(
                span=Span(_seconds(*timing.groups()[:4]),
                                      _seconds(*timing.groups()[4:])),
                text=without_loop(text),
            ))
    return utterances

class WhisperCppTranscriber:
    def __init__(self, model: Path, vad: Path | None = None, threads: int | None = None,
                 device: str = AUTO) -> None:
        if not model.exists():
            raise FileNotFoundError(f"modèle de transcription introuvable : {model}")
        self.model = model
        self.vad = vad if vad and vad.exists() else None
        self.threads = threads if threads is not None else max(1, min(4, os.cpu_count() or 1))
        self.device = device

    def warm(self) -> None:
        """Nothing to open: whisper.cpp loads its model in its own process."""

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / audio.stem
            command = [
                "whisper-cli", "-m", str(self.model), "-f", str(audio),
                "-l", language or "auto", "-t", str(self.threads), "-osrt", "-of", str(base),
            ]
            if self.device == "cpu":
                command.append("--no-gpu")
            if self.vad:
                command += ["--vad", "--vad-model", str(self.vad)]
            if prompt_seed:
                command += ["--prompt", prompt_seed]
            # Keep CPU worker pools from competing with Accelerate's own pool.
            # These defaults apply to this child only and preserve explicit settings.
            environment = dict(os.environ)
            environment.setdefault("OMP_WAIT_POLICY", "PASSIVE")
            environment.setdefault("VECLIB_MAXIMUM_THREADS", "1")
            outcome = subprocess.run(
                command, capture_output=True, text=True, check=False, env=environment,
            )
            srt = base.with_suffix(".srt")
            if outcome.returncode != 0 or not srt.exists():
                latest = (outcome.stderr or outcome.stdout).strip().splitlines()
                raise RuntimeError(
                    "whisper-cli a échoué" + (f" : {latest[-1]}" if latest else "")
                )
            return lire_srt(srt)
