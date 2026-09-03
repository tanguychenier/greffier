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

from greffier.domaine.empreintes import agreger, normaliser, similarite

audio = Path(sys.argv[1])
nb_personnes = int(sys.argv[2]) if len(sys.argv) > 2 else 0
DUREE_MINIMALE = 3.0

MODELES = Path.home() / "reunions/models/diarisation"
config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
    segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
            model=str(MODELES / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx")
        ),
    ),
    embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELES / "nemo_en_titanet_large.onnx")
    ),
    clustering=sherpa_onnx.FastClusteringConfig(
        num_clusters=nb_personnes if nb_personnes else -1, threshold=0.8
    ),
    min_duration_on=0.3,
    min_duration_off=0.5,
)
moteur = sherpa_onnx.OfflineSpeakerDiarization(config)

donnees, frequence = sf.read(audio, dtype="float32", always_2d=True)
actifs = [
    i
    for i in range(donnees.shape[1])
    if float(np.sqrt(np.mean(donnees[:, i] ** 2))) > 1e-5
]
signal = donnees[:, actifs].mean(axis=1)
print(f"{len(signal) / frequence / 60:.1f} min, {len(actifs)} canal/canaux actifs")

segments = moteur.process(signal).sort_by_start_time()
print(f"{len(segments)} segments, {len({s.speaker for s in segments})} voix distinctes")

extracteur = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELES / "nemo_en_titanet_large.onnx")
    )
)


def empreinte(debut: float, fin: float):
    flux = extracteur.create_stream()
    flux.accept_waveform(
        sample_rate=frequence,
        waveform=signal[int(debut * frequence) : int(fin * frequence)],
    )
    flux.input_finished()
    return normaliser(extracteur.compute(flux), duree_source=fin - debut)


par_voix: dict[int, list] = {}
for segment in segments:
    duree = segment.end - segment.start
    if duree < DUREE_MINIMALE:
        continue
    par_voix.setdefault(segment.speaker, []).append(empreinte(segment.start, segment.end))

print(f"\nsegments retenus (≥ {DUREE_MINIMALE:.0f} s) :")
for voix, empreintes in sorted(par_voix.items()):
    total = sum(e.duree_source for e in empreintes)
    print(f"  voix {voix} : {len(empreintes):3d} extraits, {total / 60:.1f} min de parole")

print("\n--- deux extraits d'une MÊME voix ---")
intra: list[float] = []
for voix, empreintes in sorted(par_voix.items()):
    scores = [
        similarite(empreintes[i], empreintes[j])
        for i in range(len(empreintes))
        for j in range(i + 1, len(empreintes))
    ]
    if scores:
        intra += scores
        print(
            f"  voix {voix} : médiane {statistics.median(scores):.3f}  "
            f"min {min(scores):.3f}  max {max(scores):.3f}"
        )

print("\n--- voix DIFFÉRENTES (agrégées) ---")
inter: list[float] = []
agregees = {v: agreger(e) for v, e in par_voix.items() if e}
voix_triees = sorted(agregees)
for i, a in enumerate(voix_triees):
    for b in voix_triees[i + 1 :]:
        score = similarite(agregees[a], agregees[b])
        inter.append(score)
        print(f"  voix {a} ↔ voix {b} : {score:.3f}")

if intra and inter:
    print(
        f"\nintra médiane {statistics.median(intra):.3f} | "
        f"inter médiane {statistics.median(inter):.3f}"
    )
    print(f"pire intra {min(intra):.3f} | meilleur inter {max(inter):.3f}")
