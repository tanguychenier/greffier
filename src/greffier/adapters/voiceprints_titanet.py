"""Extracting voiceprints with TitaNet, locally.

Measured against three better-ranked candidates on 931 turns of a real meeting:
CAM++ and ResNet293 have a **negative** margin on 2.5-second excerpts, meaning
no threshold separates "same person" from "different people". See
docs/rex-2026-09-10.md. TitaNet stays: +0.099 of margin at 14.6 ms per excerpt.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

from greffier.domain.arithmetic import compute_threads
from greffier.domain.models import Span, Voiceprint
from greffier.domain.voiceprints import normalise

DUREE_MINIMALE = 1.5

DUREE_MAXIMALE = 60.0

class TitaNetExtractor:
    """Turns an excerpt of speech into a voiceprint."""

    def __init__(self, model: Path) -> None:
        if not model.exists():
            raise FileNotFoundError(f"modèle d'empreintes introuvable : {model}")
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model), num_threads=compute_threads())
        )

    def extract(self, echantillons: np.ndarray, frequency: int) -> Voiceprint:
        """The voiceprint of an excerpt, capped in duration."""
        borne = int(DUREE_MAXIMALE * frequency)
        if len(echantillons) > borne:
            milieu = len(echantillons) // 2
            echantillons = echantillons[milieu - borne // 2 : milieu + borne // 2]
        flux = self._extractor.create_stream()
        flux.accept_waveform(sample_rate=frequency, waveform=echantillons)
        flux.input_finished()
        vector = self._extractor.compute(flux)
        return normalise(vector, source_duration=len(echantillons) / frequency)

    def extract_spans(
        self,
        audio: Path,
        intervalles: list[Span],
    ) -> list[Voiceprint]:
        """One voiceprint per span, the too-short ones dropped."""
        data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        signal = data.mean(axis=1)
        voiceprints: list[Voiceprint] = []
        for span in intervalles:
            if span.duration < DUREE_MINIMALE:
                continue
            start = int(span.start * frequency)
            end = min(int(span.end * frequency), len(signal))
            if end - start < DUREE_MINIMALE * frequency:
                continue
            voiceprints.append(self.extract(signal[start:end], frequency))
        return voiceprints
