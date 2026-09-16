"""Cutting a live slice at the changes of speaker, with the segmentation model.

The same pyannote model the chain uses after the meeting, run on the slice
alone. It reads audio in windows of ten seconds and tells up to three
speakers apart inside a window; across windows it would need the voiceprint
model and a clustering, which is the expensive part. A slice is therefore
read window by window, each with its own labels, and the thread joins the
windows to its voices by voiceprint as it always did: measured on the
processor under load, a ten-second window costs 0.14 s, and the same audio
read as one fifteen-second piece cost twelve seconds.
"""

from __future__ import annotations

from pathlib import Path

import sherpa_onnx
import soundfile as sf

from greffier.adapters.channels_file import split_channels
from greffier.domain.arithmetic import compute_threads
from greffier.domain.models import Source, Span, SpeakerTurn

#: What the segmentation model reads at once. Beyond it the engine runs the
#: voiceprint model on every segment to join the windows, which is what the
#: live thread does itself.
WINDOW_S = 10.0

#: Under this, a window holds no sentence worth cutting.
SHORTEST_WINDOW_S = 1.0

PROCESSOR = "cpu"


class SherpaSliceSegmenter:
    """Speaker turns inside one slice, one set of labels per window."""

    def __init__(self, segmentation: Path, voiceprints: Path) -> None:
        for model in (segmentation, voiceprints):
            if not model.exists():
                raise FileNotFoundError(f"modèle de diarisation introuvable : {model}")
        self.segmentation = segmentation
        self.voiceprints = voiceprints
        self._engine: sherpa_onnx.OfflineSpeakerDiarization | None = None

    def _the_engine(self) -> sherpa_onnx.OfflineSpeakerDiarization:
        """Opened on the first slice: the models weigh a hundred megabytes."""
        if self._engine is None:
            threads = compute_threads()
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(self.segmentation)
                    ),
                    num_threads=threads,
                    provider=PROCESSOR,
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self.voiceprints), num_threads=threads, provider=PROCESSOR
                ),
                clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.45),
                min_duration_on=0.3,
                min_duration_off=0.5,
            )
            if not config.validate():
                raise RuntimeError("configuration de segmentation invalide")
            self._engine = sherpa_onnx.OfflineSpeakerDiarization(config)
        return self._engine

    def turns(self, audio: Path) -> list[SpeakerTurn]:
        """The speaker turns of the slice, labelled window by window.

        The windows are counted from the end of the slice, so that the fresh
        seconds, the ones the thread has not shown yet, fall in one window
        whatever the overlap in front of them. Nothing comes back for a file
        the models cannot read: the thread then attributes the slice as a
        whole, as it did before.
        """
        try:
            data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        except (OSError, RuntimeError, ValueError):
            return []
        engine = self._the_engine()
        if frequency != engine.sample_rate:
            return []
        signal = split_channels(data, frequency).system
        found: list[SpeakerTurn] = []
        end = len(signal)
        window = int(WINDOW_S * frequency)
        number = 0
        while end > 0:
            start = max(0, end - window)
            piece = signal[start:end]
            if len(piece) >= SHORTEST_WINDOW_S * frequency:
                for segment in engine.process(piece).sort_by_start_time():
                    found.append(SpeakerTurn(
                        span=Span(start / frequency + segment.start,
                                  start / frequency + segment.end),
                        voice=f"{number}:{segment.speaker}",
                        source=Source.UNKNOWN,
                    ))
            end = start
            number += 1
        return sorted(found, key=lambda turn: turn.span.start)
