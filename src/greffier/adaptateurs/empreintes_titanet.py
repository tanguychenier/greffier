"""Extraction d'empreintes vocales par TitaNet, en local.

Adaptateur : c'est le seul endroit du projet qui sait que le modèle s'appelle
TitaNet et qu'il tourne sous sherpa-onnx. Le domaine, lui, ne manipule que des
vecteurs normalisés, ce qui permet de changer de modèle sans toucher aux règles.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

from greffier.domaine.empreintes import normaliser
from greffier.domaine.modeles import Empreinte, Intervalle

# En deçà, l'extrait ne porte pas assez de voix pour une empreinte fiable : le
# vecteur obtenu tient davantage du bruit de la pièce que de la personne.
DUREE_MINIMALE = 1.5

#: Au-delà, le modèle tombe. Mesuré : 120 s passent, 150 s échouent avec
#: « BroadcastIterator::Init: axis == 1 || axis == largest was false », une
#: erreur d'ONNX Runtime dans le nœud « Where » de l'encodeur. C'est arrivé sur
#: une réunion de 33 minutes tenue autour d'une table, où la segmentation avait
#: produit un long tour de parole continu.
#:
#: Soixante secondes, donc, avec de la marge : une empreinte vocale n'a pas
#: besoin de davantage, et le calibrage montre qu'elle se stabilise bien avant.
DUREE_MAXIMALE = 60.0


class ExtracteurTitaNet:
    """Transforme un extrait de parole en empreinte vocale."""

    def __init__(self, modele: Path) -> None:
        if not modele.exists():
            raise FileNotFoundError(f"modèle d'empreintes introuvable : {modele}")
        self._extracteur = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(modele))
        )

    def extraire(self, echantillons: np.ndarray, frequence: int) -> Empreinte:
        """Empreinte d'un extrait, borné en durée.

        Un extrait trop long fait tomber le modèle, et avec lui la réunion
        entière : voir `DUREE_MAXIMALE`. On garde le **milieu** du passage plutôt
        que son début, où l'on trouve volontiers une hésitation ou un « alors »
        qui ne dit rien du timbre.
        """
        borne = int(DUREE_MAXIMALE * frequence)
        if len(echantillons) > borne:
            milieu = len(echantillons) // 2
            echantillons = echantillons[milieu - borne // 2 : milieu + borne // 2]
        flux = self._extracteur.create_stream()
        flux.accept_waveform(sample_rate=frequence, waveform=echantillons)
        flux.input_finished()
        vecteur = self._extracteur.compute(flux)
        return normaliser(vecteur, duree_source=len(echantillons) / frequence)

    def extraire_intervalles(
        self,
        audio: Path,
        intervalles: list[Intervalle],
    ) -> list[Empreinte]:
        """Une empreinte par intervalle, les trop courts étant écartés.

        Les canaux sont additionnés : en visio, la voix distante n'est que sur
        l'un des deux, et n'en garder qu'un ferait disparaître la moitié des
        participants.
        """
        donnees, frequence = sf.read(audio, dtype="float32", always_2d=True)
        signal = donnees.mean(axis=1)
        empreintes: list[Empreinte] = []
        for intervalle in intervalles:
            if intervalle.duree < DUREE_MINIMALE:
                continue
            debut = int(intervalle.debut * frequence)
            fin = min(int(intervalle.fin * frequence), len(signal))
            if fin - debut < DUREE_MINIMALE * frequence:
                continue
            empreintes.append(self.extraire(signal[debut:fin], frequence))
        return empreintes
