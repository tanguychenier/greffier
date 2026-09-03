"""Applique le recollage des voix à une vraie réunion sur-découpée."""

import sys
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

sys.path.insert(0, "src")

from greffier.domaine.empreintes import agreger, fusionner_voix, normaliser, similarite

audio = Path(sys.argv[1])
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
    clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.8),
    min_duration_on=0.3,
    min_duration_off=0.5,
)
moteur = sherpa_onnx.OfflineSpeakerDiarization(config)

donnees, frequence = sf.read(audio, dtype="float32", always_2d=True)
actifs = [i for i in range(donnees.shape[1]) if float(np.sqrt(np.mean(donnees[:, i] ** 2))) > 1e-5]
signal = donnees[:, actifs].mean(axis=1)
segments = moteur.process(signal).sort_by_start_time()

extracteur = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELES / "nemo_en_titanet_large.onnx"))
)


def empreinte(debut: float, fin: float):
    flux = extracteur.create_stream()
    flux.accept_waveform(
        sample_rate=frequence, waveform=signal[int(debut * frequence) : int(fin * frequence)]
    )
    flux.input_finished()
    return normaliser(extracteur.compute(flux), duree_source=fin - debut)


par_voix: dict[str, list] = {}
duree_voix: dict[str, float] = {}
for segment in segments:
    voix = f"v{segment.speaker}"
    duree_voix[voix] = duree_voix.get(voix, 0.0) + (segment.end - segment.start)
    if segment.end - segment.start >= 3.0:
        par_voix.setdefault(voix, []).append(empreinte(segment.start, segment.end))

# Les voix trop brèves n'ont aucune empreinte exploitable : elles restent seules.
for voix in duree_voix:
    par_voix.setdefault(voix, [])

print(f"AVANT : {len(duree_voix)} voix distinctes sur {len(segments)} segments")
appartenance = fusionner_voix(par_voix)
retenues = sorted(set(appartenance.values()), key=lambda v: -duree_voix.get(v, 0))
avec_parole = [v for v in retenues if duree_voix.get(v, 0) >= 10]
print(f"APRÈS : {len(retenues)} voix, dont {len(avec_parole)} avec au moins 10 s de parole\n")

cumul: dict[str, float] = {}
for voix, vers in appartenance.items():
    cumul[vers] = cumul.get(vers, 0.0) + duree_voix.get(voix, 0.0)

total = sum(cumul.values()) or 1
for voix in sorted(cumul, key=lambda v: -cumul[v]):
    absorbees = [v for v, vers in appartenance.items() if vers == voix and v != voix]
    if cumul[voix] < 5:
        continue
    print(
        f"  {voix:5s} {cumul[voix] / 60:5.1f} min ({cumul[voix] / total * 100:4.1f} %)"
        + (f"  ← recolle {', '.join(absorbees)}" if absorbees else "")
    )

restants = {v: agreger(e) for v, e in par_voix.items() if e and appartenance[v] == v}
noms = sorted(restants)
proches = [
    (similarite(restants[a], restants[b]), a, b)
    for i, a in enumerate(noms)
    for b in noms[i + 1 :]
]
if proches:
    pire = max(proches)
    print(
        f"\nplus fort rapprochement restant entre deux voix : "
        f"{pire[0]:.3f} ({pire[1]} ↔ {pire[2]})"
    )
