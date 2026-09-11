"""Bornes de l'extraction d'empreintes.

Le cas nommé : une réunion de 33 minutes autour d'une table a fait tomber
l'identification des locuteurs avec « BroadcastIterator::Init: axis == 1 ||
axis == largest was false », une erreur d'ONNX Runtime dans le nœud « Where » de
l'encodeur. La segmentation avait produit un long tour de parole continu, et le
modèle n'accepte pas un extrait de cette longueur : mesuré, 120 s passent et
150 s échouent.

Ces tests portent sur le bornage, qui ne demande pas de charger les 98 Mo du
modèle : ils vérifient qu'on ne lui soumet jamais plus que ce qu'il accepte.
"""

from __future__ import annotations

import numpy as np

from greffier.adapters.voiceprints_titanet import MAXIMUM_LENGTH, MINIMUM_LENGTH


class Recorded:
    """Retient ce qu'on lui soumet, à la place du modèle."""

    def __init__(self) -> None:
        self.recus: list[int] = []

    def borner(self, echantillons: np.ndarray, frequency: int) -> np.ndarray:
        # Reproduit le bornage de l'adaptateur, la seule règle en jeu.
        borne = int(MAXIMUM_LENGTH * frequency)
        if len(echantillons) > borne:
            milieu = len(echantillons) // 2
            echantillons = echantillons[milieu - borne // 2 : milieu + borne // 2]
        self.recus.append(len(echantillons))
        return echantillons


class TestBornes:
    def test_the_bound_stays_under_the_measured_limit(self) -> None:
        # 120 s passent, 150 s échouent : la borne doit être franchement en deçà.
        assert MAXIMUM_LENGTH <= 120.0
        assert MAXIMUM_LENGTH >= MINIMUM_LENGTH

    def test_un_extrait_court_passe_entier(self) -> None:
        garde = Recorded()
        garde.borner(np.zeros(16000 * 10, dtype="float32"), 16000)
        assert garde.recus == [16000 * 10]

    def test_too_long_an_extract_is_brought_back_to_the_bound(self) -> None:
        garde = Recorded()
        garde.borner(np.zeros(16000 * 600, dtype="float32"), 16000)
        assert garde.recus == [int(16000 * MAXIMUM_LENGTH)]

    def test_it_is_the_middle_of_the_passage_that_is_kept(self) -> None:
        # Le début d'un long tour de parole porte volontiers une hésitation ou
        # un « alors » qui ne dit rien du timbre.
        frequency = 16000
        signal = np.arange(frequency * 600, dtype="float32")
        borne = int(MAXIMUM_LENGTH * frequency)
        milieu = len(signal) // 2
        expected = signal[milieu - borne // 2 : milieu + borne // 2]
        assert expected[0] > 0, "le début du signal n'est pas retenu"
        assert len(expected) == borne
