"""Cutting into speaker turns, through sherpa-onnx.

Over-segmenting and stitching back is reversible; under-segmenting is not. The
grouping threshold is therefore deliberately low, and the stitching in the
domain repairs afterwards.
"""

from __future__ import annotations

from pathlib import Path

import sherpa_onnx
import soundfile as sf

from greffier.adapters.channels_file import TRAME_S, levels_per_frame, separer_canaux
from greffier.domain.arithmetic import compute_threads
from greffier.domain.channels import VOIX_LOCALE, local_turns, remove
from greffier.domain.models import Source, Span, SpeakerTurn


class SherpaDiariser:
    def __init__(self, segmentation: Path, voiceprints: Path, seuil: float = 0.45) -> None:
        for model in (segmentation, voiceprints):
            if not model.exists():
                raise FileNotFoundError(f"modèle de diarisation introuvable : {model}")
        self.segmentation = segmentation
        self.voiceprints = voiceprints
        self.seuil = seuil

    def segment(self, audio: Path, people: int | None) -> list[SpeakerTurn]:
        fils = compute_threads()
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(self.segmentation)
                ),
                num_threads=fils,
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.voiceprints), num_threads=fils),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=people if people else -1, threshold=self.seuil
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError("configuration de diarisation invalide")
        engine = sherpa_onnx.OfflineSpeakerDiarization(config)

        data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        if frequency != engine.sample_rate:
            raise ValueError(
                f"{audio} est en {frequency} Hz, les modèles attendent {engine.sample_rate} Hz."
            )

        channels = separer_canaux(data, frequency)
        mic, system, distante = channels.mic, channels.system, channels.distante
        locaux = (
            local_turns(
                levels_per_frame(mic, frequency),
                levels_per_frame(system, frequency),
                TRAME_S,
            )
            if distante and mic is not None
            else []
        )
        a_segmenter = system if distante else (mic if mic is not None else system)

        distants = [
            SpeakerTurn(
                span=Span(s.start, s.end),
                voice=str(s.speaker),
                source=Source.SYSTEM if distante else Source.INCONNUE,
            )
            for s in engine.process(a_segmenter).sort_by_start_time()
        ]
        gardes = remove([t.span for t in distants], locaux)
        distants = [t for t in distants if t.span in gardes]

        turns = distants + [
            SpeakerTurn(span=x, voice=VOIX_LOCALE, source=Source.MIC)
            for x in locaux
        ]
        return sorted(turns, key=lambda t: t.span.start)
