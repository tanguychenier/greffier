"""Extracting voiceprints with TitaNet, locally.

Measured against three better-ranked candidates on 931 turns of a real meeting:
CAM++ and ResNet293 have a **negative** margin on 2.5-second excerpts, meaning
no threshold separates "same person" from "different people". See
docs/retrospective-2026-09-10.md. TitaNet stays: +0.099 of margin at 14.6 ms per excerpt.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import sherpa_onnx
import soundfile as sf

from greffier.adapters import cuda
from greffier.domain.arithmetic import AUTO, CARD, chosen_device, compute_threads
from greffier.domain.models import Span, Voiceprint
from greffier.domain.voiceprints import at_a_common_level, normalise

MINIMUM_LENGTH = 1.5

MAXIMUM_LENGTH = 60.0

_OPENED: dict[tuple[str, str], Any] = {}

_TURN = threading.Lock()

class TitaNetExtractor:
    """Turns an excerpt of speech into a voiceprint."""

    def __init__(self, model: Path, device: str = AUTO) -> None:
        if not model.exists():
            raise FileNotFoundError(f"modèle d'empreintes introuvable : {model}")
        self.model = model
        self.device = chosen_device(device, cuda.a_card_is_usable())

    @property
    def _extractor(self) -> Any:
        """The model, opened once per file and device for the whole process.

        It weighs a hundred megabytes and is built afresh every time a voice is
        named or split. Opened here rather than in the instance, the second
        click pays nothing.
        """
        clef = (str(self.model), self.device)
        with _TURN:
            ready = _OPENED.get(clef)
            if ready is None:
                if self.device == CARD:
                    cuda.show_to_the_loader()
                ready = sherpa_onnx.SpeakerEmbeddingExtractor(
                    sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                        model=str(self.model), num_threads=compute_threads(),
                        provider=self.device)
                )
                _OPENED[clef] = ready
        return ready

    def extract(self, samples: np.ndarray, frequency: int) -> Voiceprint:
        """The voiceprint of an excerpt, capped in duration and levelled.

        Levelled because the model is not level-invariant: the same excerpt
        attenuated by 24 dB comes back at 0.874 of itself, and the thresholds
        that tell one person from two sit between 0.45 and 0.75.
        """
        borne = int(MAXIMUM_LENGTH * frequency)
        if len(samples) > borne:
            milieu = len(samples) // 2
            samples = samples[milieu - borne // 2 : milieu + borne // 2]
        at_level = np.asarray(at_a_common_level(samples.tolist()), dtype="float32")
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=frequency, waveform=at_level)
        stream.input_finished()
        vector = self._extractor.compute(stream)
        return normalise(vector, source_duration=len(samples) / frequency)

    def extract_together(self, audio: Path, the_spans: list[Span]) -> Voiceprint | None:
        """One voiceprint for all these passages at once, or None.

        A real conversation is made of short turns: measured on a meeting round
        a table, the median passage lasts 1.57 s and a quarter of them are under
        0.66 s, while the model asks for 1.5 s. Forty-five of the hundred and
        twenty-one voices the segmenter produced therefore carried no voiceprint
        at all, and nothing could ever join them: they stayed separate people,
        one per « oui » and per « d'accord ».

        Taken together they are the same voice by the segmenter's own verdict,
        so they are cut out and read as one excerpt.
        """
        data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        signal = data.mean(axis=1)
        chunks = []
        for span in sorted(the_spans, key=lambda s: s.start):
            start = max(0, int(span.start * frequency))
            end = min(int(span.end * frequency), len(signal))
            if end > start:
                chunks.append(signal[start:end])
        if not chunks:
            return None
        ensemble = np.concatenate(chunks)
        if len(ensemble) < MINIMUM_LENGTH * frequency:
            return None
        return self.extract(ensemble, frequency)

    def extract_spans(
        self,
        audio: Path,
        the_spans: list[Span],
    ) -> list[Voiceprint]:
        """One voiceprint per span, the too-short ones dropped."""
        data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        signal = data.mean(axis=1)
        voiceprints: list[Voiceprint] = []
        for span in the_spans:
            if span.duration < MINIMUM_LENGTH:
                continue
            start = int(span.start * frequency)
            end = min(int(span.end * frequency), len(signal))
            if end - start < MINIMUM_LENGTH * frequency:
                continue
            voiceprints.append(self.extract(signal[start:end], frequency))
        return voiceprints
