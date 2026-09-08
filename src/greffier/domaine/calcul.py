"""Combien de fils laisser aux modèles, et pourquoi pas tous.

Sans rien de sherpa ni d'onnx ici : c'est une règle, pas un adaptateur, et une
règle se teste sans charger un modèle d'un gigaoctet.
"""

from __future__ import annotations

import os


def fils_de_calcul(coeurs: int | None = None) -> int:
    """La moitié des cœurs, au moins un.

    Les modèles ONNX n'en prennent qu'un par défaut : sur huit cœurs, sept
    restaient inoccupés pendant que la segmentation et les empreintes — la
    partie la plus longue du traitement — faisaient attendre la réunion.

    La moitié, et non la totalité, parce que c'est ce que la mesure donne. Sur
    ce poste à huit cœurs, la diarisation d'un entretien de cent cinq secondes
    prend 287 s sur un fil, 206 s sur deux, 167 s sur quatre, et **193 s sur
    huit** : tout prendre est moins bon que la moitié. Ce qui reste sert aussi
    à garder le poste utilisable, la veille tournant pendant la réunion.
    """
    disponibles = coeurs if coeurs is not None else (os.cpu_count() or 2)
    return max(1, disponibles // 2)
