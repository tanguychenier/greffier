"""Applique le recollage des voix à une vraie réunion sur-découpée."""

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
actifs = [i for i in range(data.shape[1]) if float(np.sqrt(np.mean(data[:, i] ** 2))) > 1e-5]
signal = data[:, actifs].mean(axis=1)
segments = engine.process(signal).sort_by_start_time()

extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / "nemo_en_titanet_large.onnx"))
)


def voiceprint(start: float, end: float):
    flux = extractor.create_stream()
    flux.accept_waveform(
        sample_rate=frequency, waveform=signal[int(start * frequency) : int(end * frequency)]
    )
    flux.input_finished()
    return normalise(extractor.compute(flux), source_duration=end - start)


per_voice: dict[str, list] = {}
duree_voix: dict[str, float] = {}
for segment in segments:
    voice = f"v{segment.speaker}"
    duree_voix[voice] = duree_voix.get(voice, 0.0) + (segment.end - segment.start)
    if segment.end - segment.start >= 3.0:
        per_voice.setdefault(voice, []).append(voiceprint(segment.start, segment.end))

# Les voix trop brèves n'ont aucune empreinte exploitable : elles restent seules.
for voice in duree_voix:
    per_voice.setdefault(voice, [])

print(f"AVANT : {len(duree_voix)} voix distinctes sur {len(segments)} segments")
membership = join_voices(per_voice)
retenues = sorted(set(membership.values()), key=lambda v: -duree_voix.get(v, 0))
avec_parole = [v for v in retenues if duree_voix.get(v, 0) >= 10]
print(f"APRÈS : {len(retenues)} voix, dont {len(avec_parole)} avec au moins 10 s de parole\n")

cumul: dict[str, float] = {}
for voice, vers in membership.items():
    cumul[vers] = cumul.get(vers, 0.0) + duree_voix.get(voice, 0.0)

total = sum(cumul.values()) or 1
for voice in sorted(cumul, key=lambda v: -cumul[v]):
    absorbees = [v for v, vers in membership.items() if vers == voice and v != voice]
    if cumul[voice] < 5:
        continue
    print(
        f"  {voice:5s} {cumul[voice] / 60:5.1f} min ({cumul[voice] / total * 100:4.1f} %)"
        + (f"  ← recolle {', '.join(absorbees)}" if absorbees else "")
    )

restants = {v: aggregate(e) for v, e in per_voice.items() if e and membership[v] == v}
names = sorted(restants)
near_ones = [
    (similarity(restants[a], restants[b]), a, b)
    for i, a in enumerate(names)
    for b in names[i + 1 :]
]
if near_ones:
    pire = max(near_ones)
    print(
        f"\nplus fort rapprochement restant entre deux voix : "
        f"{pire[0]:.3f} ({pire[1]} ↔ {pire[2]})"
    )
