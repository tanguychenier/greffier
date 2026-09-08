"""Ce qui reste d'un texte quand un système de fichiers ne veut que de l'ASCII.

Sans dépendance, et sans rien de Greffier : trois endroits réduisent un texte
libre en identifiant, et ils ont besoin du même filet quand la réduction ne
laisse rien.
"""

from __future__ import annotations

import hashlib


def empreinte_courte(texte: str) -> str:
    """Un identifiant stable dérivé du texte, quand la réduction rend le vide.

    Une réduction à l'ASCII efface entièrement un nom cyrillique, grec, arabe
    ou idéographique. Se rabattre alors sur un mot fixe — « sans-nom »,
    « reunion » — donne le MÊME identifiant à des textes différents : deux
    personnes distinctes se retrouvaient sous une seule empreinte dans la
    banque de voix, ce qui n'est pas un défaut d'affichage mais une fusion de
    données. Une empreinte du texte d'origine sépare ce que la réduction avait
    confondu.

    Dix caractères : assez pour que deux noms d'une réunion ne se croisent
    jamais, assez court pour rester lisible dans un nom de fichier. Stable d'une
    exécution à l'autre, contrairement à `hash`, sans quoi une voix nommée
    aujourd'hui ne serait plus reconnue demain.
    """
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:10]
