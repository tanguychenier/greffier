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

from greffier.domain.arithmetic import compute_threads
from greffier.domain.models import Span, Voiceprint
from greffier.domain.voiceprints import normalise

# En deçà, l'extrait ne porte pas assez de voix pour une empreinte fiable : le
# vecteur obtenu tient davantage du bruit de la pièce que de la personne.
DUREE_MINIMALE = 1.5

DUREE_MAXIMALE = 60.0

class ExtracteurTitaNet:
    """Transforme un extrait de parole en empreinte vocale."""

    def __init__(self, model: Path) -> None:
        if not model.exists():
            raise FileNotFoundError(f"modèle d'empreintes introuvable : {model}")
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model), num_threads=compute_threads())
        )

    def extract(self, echantillons: np.ndarray, frequency: int) -> Voiceprint:
        """Empreinte d'un extrait, borné en durée.

        Un extrait trop long fait tomber le modèle, et avec lui la réunion
        entière : voir `DUREE_MAXIMALE`. On garde le **milieu** du passage plutôt
        que son début, où l'on trouve volontiers une hésitation ou un « alors »
        qui ne dit rien du timbre.
        """
        borne = int(DUREE_MAXIMALE * frequency)
        if len(echantillons) > borne:
            milieu = len(echantillons) // 2
            echantillons = echantillons[milieu - borne // 2 : milieu + borne // 2]
        flux = self._extractor.create_stream()
        flux.accept_waveform(sample_rate=frequency, waveform=echantillons)
        flux.input_finished()
        vector = self._extractor.compute(flux)
        return normalise(vector, source_duration=len(echantillons) / frequency)

    def extract_spans(
        self,
        audio: Path,
        intervalles: list[Span],
    ) -> list[Voiceprint]:
        """Une empreinte par intervalle, les trop courts étant écartés.

        Les canaux sont additionnés : en visio, la voix distante n'est que sur
        l'un des deux, et n'en garder qu'un ferait disparaître la moitié des
        participants.
        """
        data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        signal = data.mean(axis=1)
        voiceprints: list[Voiceprint] = []
        for span in intervalles:
            if span.duration < DUREE_MINIMALE:
                continue
            start = int(span.start * frequency)
            end = min(int(span.end * frequency), len(signal))
            if end - start < DUREE_MINIMALE * frequency:
                continue
            voiceprints.append(self.extract(signal[start:end], frequency))
        return voiceprints
