"""Calibrage sur les segments exacts de la diarisation.

La première mesure reposait sur des tours reconstruits depuis un fichier texte,
donc bourrés de silences : les empreintes en sortaient bruitées. Ici on relance
la segmentation pour obtenir les bornes réelles de chaque prise de parole, et on
ne garde que les extraits assez longs pour porter un timbre.
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
nb_personnes = int(sys.argv[2]) if len(sys.argv) > 2 else 0
DUREE_MINIMALE = 3.0

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
        num_clusters=nb_personnes if nb_personnes else -1, threshold=0.8
    ),
    min_duration_on=0.3,
    min_duration_off=0.5,
)
engine = sherpa_onnx.OfflineSpeakerDiarization(config)

data, frequency = sf.read(audio, dtype="float32", always_2d=True)
actifs = [
    i
    for i in range(data.shape[1])
    if float(np.sqrt(np.mean(data[:, i] ** 2))) > 1e-5
]
signal = data[:, actifs].mean(axis=1)
print(f"{len(signal) / frequency / 60:.1f} min, {len(actifs)} canal/canaux actifs")

segments = engine.process(signal).sort_by_start_time()
print(f"{len(segments)} segments, {len({s.speaker for s in segments})} voix distinctes")

extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELS / "nemo_en_titanet_large.onnx")
    )
)


def voiceprint(start: float, end: float):
    flux = extractor.create_stream()
    flux.accept_waveform(
        sample_rate=frequency,
        waveform=signal[int(start * frequency) : int(end * frequency)],
    )
    flux.input_finished()
    return normalise(extractor.compute(flux), source_duration=end - start)


per_voice: dict[int, list] = {}
for segment in segments:
    duration = segment.end - segment.start
    if duration < DUREE_MINIMALE:
        continue
    per_voice.setdefault(segment.speaker, []).append(voiceprint(segment.start, segment.end))

print(f"\nsegments retenus (≥ {DUREE_MINIMALE:.0f} s) :")
for voice, voiceprints in sorted(per_voice.items()):
    total = sum(e.source_duration for e in voiceprints)
    print(f"  voix {voice} : {len(voiceprints):3d} extraits, {total / 60:.1f} min de parole")

print("\n--- deux extraits d'une MÊME voix ---")
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
            f"  voix {voice} : médiane {statistics.median(scores):.3f}  "
            f"min {min(scores):.3f}  max {max(scores):.3f}"
        )

print("\n--- voix DIFFÉRENTES (agrégées) ---")
inter: list[float] = []
agregees = {v: aggregate(e) for v, e in per_voice.items() if e}
voix_triees = sorted(agregees)
for i, a in enumerate(voix_triees):
    for b in voix_triees[i + 1 :]:
        score = similarity(agregees[a], agregees[b])
        inter.append(score)
        print(f"  voix {a} ↔ voix {b} : {score:.3f}")

if intra and inter:
    print(
        f"\nintra médiane {statistics.median(intra):.3f} | "
        f"inter médiane {statistics.median(inter):.3f}"
    )
    print(f"pire intra {min(intra):.3f} | meilleur inter {max(inter):.3f}")
