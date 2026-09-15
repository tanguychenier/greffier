"""Transcription through faster-whisper, everywhere whisper.cpp is not."""

from __future__ import annotations

import contextlib
import math
import threading
from pathlib import Path
from typing import Any

from greffier.adapters import cuda
from greffier.domain.models import Span, Utterance
from greffier.domain.transcription import without_loop

_OPENED: dict[tuple[str, str], Any] = {}

_TOUR = threading.Lock()

class FasterWhisperTranscriber:
    def __init__(self, taille: str = "large-v3", device: str = "auto") -> None:
        self.taille = taille
        self.device = device
        self._model = None

    def _load(self) -> object:
        """The model, opened once per size and device for the whole process.

        Opening large-v3 takes twelve to nineteen seconds -- longer than
        transcribing forty seconds of meeting. Kept here rather than in the
        instance so that a model opened while the recording is being closed
        serves the chain that comes right after.
        """
        if self._model is None:
            clef = (self.taille, self.device)
            with _TOUR:
                model = _OPENED.get(clef)
                if model is None:
                    cuda.show_to_the_loader()
                    from faster_whisper import WhisperModel

                    model = WhisperModel(
                        self.taille, device=self.device, compute_type="int8"
                    )
                    _OPENED[clef] = model
            self._model = model
        return self._model

    def warm(self) -> None:
        """Opens the model now, without transcribing anything.

        Called from a thread while something else is already taking time: a
        failure here costs nothing, since the chain will open it again and say
        so properly.
        """
        with contextlib.suppress(Exception):
            self._load()

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        try:
            return self._utterances(audio, language, prompt_seed)
        except RuntimeError:
            if self.device == "cpu":
                raise
            _OPENED.pop((self.taille, self.device), None)
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
                      text=without_loop(s.text.strip()),
                      confidence=_how_sure(s))
            for s in segments
            if s.text.strip()
        ]


def _how_sure(segment: object) -> float | None:
    """The model's own certainty about a segment, between 0 and 1.

    Whisper gives `avg_logprob`, the mean log probability of the tokens it
    chose. Its exponential is the average probability per token, which is the
    figure the literature uses and the only one comparable from one segment to
    the next -- a log probability alone says nothing without the length.

    None rather than a guess where the engine did not say: a turn nobody can
    judge must not be shown as a turn the tool doubts.
    """
    mean = getattr(segment, "avg_logprob", None)
    if mean is None:
        return None
    try:
        return min(1.0, max(0.0, math.exp(float(mean))))
    except (OverflowError, TypeError, ValueError):
        return None
