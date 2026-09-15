"""Calibration on the exact segments of the diarisation.

The first measurement rested on turns rebuilt from a text file, hence full of
silences: the voiceprints came out noisy. Here the segmentation is run again
to get the real boundaries of every stretch of speech, and only the excerpts
long enough to carry a timbre are kept.
"""

import statistics
import sys
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

sys.path.insert(0, "src")

from greffier.domain.voiceprints import aggregate, normalise, similarity

audio = Path(sys.argv[1])
people = int(sys.argv[2]) if len(sys.argv) > 2 else 0
MINIMUM_LENGTH = 3.0

MODELS = Path.home() / "reunions/models/diarisation"
config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
    segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
            model=str(MODELS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx")
        ),
    ),
    embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELS / "nemo_en_titanet_large.onnx")
    ),
    clustering=sherpa_onnx.FastClusteringConfig(
        num_clusters=people if people else -1, threshold=0.8
    ),
    min_duration_on=0.3,
    min_duration_off=0.5,
)
engine = sherpa_onnx.OfflineSpeakerDiarization(config)

data, frequency = sf.read(audio, dtype="float32", always_2d=True)
active = [
    i
    for i in range(data.shape[1])
    if float(np.sqrt(np.mean(data[:, i] ** 2))) > 1e-5
]
signal = data[:, active].mean(axis=1)
print(f"{len(signal) / frequency / 60:.1f} min, {len(active)} active channel(s)")

segments = engine.process(signal).sort_by_start_time()
print(f"{len(segments)} segments, {len({s.speaker for s in segments})} distinct voices")

extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELS / "nemo_en_titanet_large.onnx")
    )
)


def voiceprint(start: float, end: float):
    stream = extractor.create_stream()
    stream.accept_waveform(
        sample_rate=frequency,
        waveform=signal[int(start * frequency) : int(end * frequency)],
    )
    stream.input_finished()
    return normalise(extractor.compute(stream), source_duration=end - start)


per_voice: dict[int, list] = {}
for segment in segments:
    duration = segment.end - segment.start
    if duration < MINIMUM_LENGTH:
        continue
    per_voice.setdefault(segment.speaker, []).append(voiceprint(segment.start, segment.end))

print(f"\nsegments kept (≥ {MINIMUM_LENGTH:.0f} s):")
for voice, voiceprints in sorted(per_voice.items()):
    total = sum(e.source_duration for e in voiceprints)
    print(f"  voice {voice}: {len(voiceprints):3d} excerpts, {total / 60:.1f} min of speech")

print("\n--- two excerpts of the SAME voice ---")
intra: list[float] = []
for voice, voiceprints in sorted(per_voice.items()):
    scores = [
        similarity(voiceprints[i], voiceprints[j])
        for i in range(len(voiceprints))
        for j in range(i + 1, len(voiceprints))
    ]
    if scores:
        intra += scores
        print(
            f"  voice {voice}: median {statistics.median(scores):.3f}  "
            f"min {min(scores):.3f}  max {max(scores):.3f}"
        )

print("\n--- DIFFERENT voices (aggregated) ---")
inter: list[float] = []
aggregated = {v: aggregate(e) for v, e in per_voice.items() if e}
sorted_voices = sorted(aggregated)
for i, a in enumerate(sorted_voices):
    for b in sorted_voices[i + 1 :]:
        score = similarity(aggregated[a], aggregated[b])
        inter.append(score)
        print(f"  voice {a} ↔ voice {b}: {score:.3f}")

if intra and inter:
    print(
        f"\nintra median {statistics.median(intra):.3f} | "
        f"inter median {statistics.median(inter):.3f}"
    )
    print(f"worst intra {min(intra):.3f} | best inter {max(inter):.3f}")
