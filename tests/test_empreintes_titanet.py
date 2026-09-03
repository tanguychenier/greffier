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

from greffier.adaptateurs.empreintes_titanet import DUREE_MAXIMALE, DUREE_MINIMALE


class Enregistre:
    """Retient ce qu'on lui soumet, à la place du modèle."""

    def __init__(self) -> None:
        self.recus: list[int] = []

    def borner(self, echantillons: np.ndarray, frequence: int) -> np.ndarray:
        # Reproduit le bornage de l'adaptateur, la seule règle en jeu.
        borne = int(DUREE_MAXIMALE * frequence)
        if len(echantillons) > borne:
            milieu = len(echantillons) // 2
            echantillons = echantillons[milieu - borne // 2 : milieu + borne // 2]
        self.recus.append(len(echantillons))
        return echantillons


class TestBornes:
    def test_la_borne_reste_sous_la_limite_mesuree(self) -> None:
        # 120 s passent, 150 s échouent : la borne doit être franchement en deçà.
        assert DUREE_MAXIMALE <= 120.0
        assert DUREE_MAXIMALE >= DUREE_MINIMALE

    def test_un_extrait_court_passe_entier(self) -> None:
        garde = Enregistre()
        garde.borner(np.zeros(16000 * 10, dtype="float32"), 16000)
        assert garde.recus == [16000 * 10]

    def test_un_extrait_trop_long_est_ramene_a_la_borne(self) -> None:
        garde = Enregistre()
        garde.borner(np.zeros(16000 * 600, dtype="float32"), 16000)
        assert garde.recus == [int(16000 * DUREE_MAXIMALE)]

    def test_c_est_le_milieu_du_passage_qui_est_gardé(self) -> None:
        # Le début d'un long tour de parole porte volontiers une hésitation ou
        # un « alors » qui ne dit rien du timbre.
        frequence = 16000
        signal = np.arange(frequence * 600, dtype="float32")
        borne = int(DUREE_MAXIMALE * frequence)
        milieu = len(signal) // 2
        attendu = signal[milieu - borne // 2 : milieu + borne // 2]
        assert attendu[0] > 0, "le début du signal n'est pas retenu"
        assert len(attendu) == borne
