"""Comparer deux versions, pour savoir s'il y a mieux ailleurs.

Écrit ici parce que c'est une règle et non un appel réseau : « 0.10.0 » est
postérieur à « 0.9.0 », ce qu'une comparaison de chaînes affirme exactement à
l'envers. C'est le genre d'erreur qui ne se voit qu'au dixième incrément, soit
des mois après la mise en service.

Trois nombres, séparés par des points, éventuellement précédés d'un « v » et
suivis d'un suffixe qu'on ignore : « v1.2.3 » et « 1.2.3-essai » désignent la
même version pour ce qui nous occupe. Ce qu'on ne sait pas lire n'est pas une
version : on refuse de conclure plutôt que de proposer une mise à jour vers
quelque chose d'incompris.
"""

from __future__ import annotations

import re

_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")


def read(brute: str) -> tuple[int, int, int] | None:
    """Les trois nombres d'une version, ou None si ce n'en est pas une."""
    trouve = _VERSION.match(brute.strip())
    if trouve is None:
        return None
    majeure, mineure, corrective = trouve.groups()
    return (int(majeure), int(mineure), int(corrective or 0))


def is_newer(candidate: str, installed: str) -> bool:
    """Vrai si `candidate` est postérieure à `installee`, strictement.

    Faux dès que l'une des deux est illisible : ne rien proposer vaut mieux que
    proposer d'installer ce qu'on n'a pas su lire.
    """
    une, autre = read(candidate), read(installed)
    if une is None or autre is None:
        return False
    return une > autre
