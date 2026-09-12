"""Transcription through faster-whisper, everywhere whisper.cpp is not."""

from __future__ import annotations

from pathlib import Path

from greffier.adapters import cuda
from greffier.domain.models import Span, Utterance
from greffier.domain.transcription import without_loop


class FasterWhisperTranscriber:
    def __init__(self, taille: str = "large-v3", device: str = "auto") -> None:
        self.taille = taille
        self.device = device
        self._model = None

    def _load(self) -> object:
        if self._model is None:
            cuda.show_to_the_loader()
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.taille, device=self.device, compute_type="int8"
            )
        return self._model

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        try:
            return self._utterances(audio, language, prompt_seed)
        except RuntimeError:
            if self.device == "cpu":
                raise
            self.device = "cpu"
            self._model = None
            return self._utterances(audio, language, prompt_seed)

    def _utterances(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        segments, _ = self._load().transcribe(  # type: ignore[attr-defined]
            str(audio),
            language=language or None,
            initial_prompt=prompt_seed or None,
            vad_filter=True,
        )
        return [
            Utterance(span=Span(s.start, s.end),
                      text=without_loop(s.text.strip()))
            for s in segments
            if s.text.strip()
        ]
