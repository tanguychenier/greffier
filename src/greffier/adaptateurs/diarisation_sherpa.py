"""Découpage en tours de parole, par sherpa-onnx, en local.

Deux modèles : pyannote-segmentation-3.0 repère quand quelqu'un parle, TitaNet
regroupe les passages par empreinte vocale.

**Les canaux ne sont pas mélangés.** L'enregistrement sépare matériellement le
micro de la boucle système : la segmentation ne tourne donc que sur la boucle,
et la voix locale est établie par le canal, ce qui ne demande aucun modèle.

Le mélange, lui, coûtait cher. Sur une réunion réelle, la voix de la personne
qui enregistrait arrivait 12 dB sous celle des autres : moyennée, elle passait
18 dB sous le mélange et n'a jamais été vue. Treize minutes de parole absentes
du compte rendu d'une réunion d'une heure.
"""

from __future__ import annotations

from pathlib import Path

import sherpa_onnx
import soundfile as sf

from greffier.adaptateurs.canaux_fichier import TRAME_S, niveaux_par_trame, separer_canaux
from greffier.domaine.canaux import VOIX_LOCALE, retirer, tours_locaux
from greffier.domaine.modeles import Intervalle, Source, TourDeParole


class DiariseurSherpa:
    def __init__(self, segmentation: Path, empreintes: Path, seuil: float = 0.45) -> None:
        for modele in (segmentation, empreintes):
            if not modele.exists():
                raise FileNotFoundError(f"modèle de diarisation introuvable : {modele}")
        self.segmentation = segmentation
        self.empreintes = empreintes
        self.seuil = seuil

    def decouper(self, audio: Path, personnes: int | None) -> list[TourDeParole]:
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(self.segmentation)
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.empreintes)),
            # Sans nombre imposé, le regroupement se fait au seuil : il sur-découpe,
            # et c'est le recollage du domaine qui remet les voix ensemble.
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=personnes if personnes else -1, threshold=self.seuil
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError("configuration de diarisation invalide")
        moteur = sherpa_onnx.OfflineSpeakerDiarization(config)

        donnees, frequence = sf.read(audio, dtype="float32", always_2d=True)
        if frequence != moteur.sample_rate:
            raise ValueError(
                f"{audio} est en {frequence} Hz, les modèles attendent {moteur.sample_rate} Hz."
            )

        canaux = separer_canaux(donnees, frequence)
        micro, systeme, distante = canaux.micro, canaux.systeme, canaux.distante
        # En présentiel, tout le monde parle dans le même micro : la provenance
        # ne distingue plus personne, et il n'y a pas de « moi » à isoler. C'est
        # le cas d'un portable posé au milieu d'une table, où la boucle système
        # ne porte rien.
        locaux = (
            tours_locaux(
                niveaux_par_trame(micro, frequence),
                niveaux_par_trame(systeme, frequence),
                TRAME_S,
            )
            if distante and micro is not None
            else []
        )
        a_segmenter = systeme if distante else (micro if micro is not None else systeme)

        distants = [
            TourDeParole(
                intervalle=Intervalle(s.start, s.end),
                voix=str(s.speaker),
                source=Source.SYSTEME if distante else Source.INCONNUE,
            )
            for s in moteur.process(a_segmenter).sort_by_start_time()
        ]
        # La segmentation ne voit que la boucle, mais un participant qui parle en
        # même temps laisse un tour à cheval sur un tour local. Le canal ne se
        # trompe pas sur la provenance : c'est lui qui tranche.
        gardes = retirer([t.intervalle for t in distants], locaux)
        distants = [t for t in distants if t.intervalle in gardes]

        tours = distants + [
            TourDeParole(intervalle=x, voix=VOIX_LOCALE, source=Source.MICRO)
            for x in locaux
        ]
        return sorted(tours, key=lambda t: t.intervalle.debut)
