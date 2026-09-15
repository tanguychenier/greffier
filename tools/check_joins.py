"""Applies the stitching of the voices to a real over-segmented meeting."""

import sys
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

sys.path.insert(0, "src")

from greffier.domain.voiceprints import aggregate, join_voices, normalise, similarity

audio = Path(sys.argv[1])
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
    clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.8),
    min_duration_on=0.3,
    min_duration_off=0.5,
)
engine = sherpa_onnx.OfflineSpeakerDiarization(config)

data, frequency = sf.read(audio, dtype="float32", always_2d=True)
active = [i for i in range(data.shape[1]) if float(np.sqrt(np.mean(data[:, i] ** 2))) > 1e-5]
signal = data[:, active].mean(axis=1)
segments = engine.process(signal).sort_by_start_time()

extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / "nemo_en_titanet_large.onnx"))
)


def voiceprint(start: float, end: float):
    stream = extractor.create_stream()
    stream.accept_waveform(
        sample_rate=frequency, waveform=signal[int(start * frequency) : int(end * frequency)]
    )
    stream.input_finished()
    return normalise(extractor.compute(stream), source_duration=end - start)


per_voice: dict[str, list] = {}
voice_duration: dict[str, float] = {}
for segment in segments:
    voice = f"v{segment.speaker}"
    voice_duration[voice] = voice_duration.get(voice, 0.0) + (segment.end - segment.start)
    if segment.end - segment.start >= 3.0:
        per_voice.setdefault(voice, []).append(voiceprint(segment.start, segment.end))

# Voices too brief have no usable voiceprint: they stay alone.
for voice in voice_duration:
    per_voice.setdefault(voice, [])

print(f"BEFORE: {len(voice_duration)} distinct voices over {len(segments)} segments")
membership = join_voices(per_voice)
kept = sorted(set(membership.values()), key=lambda v: -voice_duration.get(v, 0))
with_speech = [v for v in kept if voice_duration.get(v, 0) >= 10]
print(f"AFTER: {len(kept)} voices, {len(with_speech)} of them with at least 10 s of speech\n")

cumulated: dict[str, float] = {}
for voice, into in membership.items():
    cumulated[into] = cumulated.get(into, 0.0) + voice_duration.get(voice, 0.0)

total = sum(cumulated.values()) or 1
for voice in sorted(cumulated, key=lambda v: -cumulated[v]):
    absorbed = [v for v, into in membership.items() if into == voice and v != voice]
    if cumulated[voice] < 5:
        continue
    print(
        f"  {voice:5s} {cumulated[voice] / 60:5.1f} min ({cumulated[voice] / total * 100:4.1f} %)"
        + (f"  ← joins {', '.join(absorbed)}" if absorbed else "")
    )

remaining = {v: aggregate(e) for v, e in per_voice.items() if e and membership[v] == v}
names = sorted(remaining)
near_ones = [
    (similarity(remaining[a], remaining[b]), a, b)
    for i, a in enumerate(names)
    for b in names[i + 1 :]
]
if near_ones:
    worst = max(near_ones)
    print(
        f"\nstrongest remaining closeness between two voices: "
        f"{worst[0]:.3f} ({worst[1]} ↔ {worst[2]})"
    )
