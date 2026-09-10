"""Où poser les nœuds d'une carte sur un plan.

Séparé de l'adaptateur qui écrit : disposer un arbre est un calcul, et un
calcul se vérifie sans réseau. Le contraire — des coordonnées décidées au fil
des appels d'API — est ce qui produit des cartes illisibles qu'il faut réagencer
à la souris.

La disposition est en **colonnes par profondeur** : la racine à gauche, ses
branches dans la colonne suivante, et ainsi de suite. Pas en éventail autour du
centre, malgré l'habitude des cartes mentales : un éventail demande de connaître
l'emprise réelle de chaque objet pour éviter les chevauchements, et l'emprise
rendue par l'API n'est pas fiable — mesuré sur un widget dont la géométrie
annonçait 2,8 fois moins large que le rendu. Des colonnes, elles, ne peuvent pas
se chevaucher horizontalement.

Les espacements sont **larges** pour la même raison : mieux vaut une carte trop
aérée qu'une carte dont les textes se recouvrent.
"""

from __future__ import annotations

from dataclasses import dataclass

from greffier.domain.board import Board, Node

WIDTH = 220
ENTRE_COLONNES = 380

ENTRE_LIGNES = 170

@dataclass(frozen=True, slots=True)
class Slot:
    """Un nœud et l'endroit où il va."""

    noeud: Node
    x: int
    y: int
    parent: str = ""

def disposer(board: Board) -> list[Slot]:
    """Les places de tous les nœuds, racine comprise.

    Chaque sous-arbre reçoit une bande verticale proportionnelle au nombre de
    feuilles qu'il porte, et son parent se centre sur cette bande : c'est ce qui
    fait qu'une branche chargée ne recouvre pas sa voisine.
    """
    if board.racine is None:
        return []
    places: list[Slot] = []
    _place(board.racine, profondeur=0, haut=0, places=places, parent="")
    return places

def _feuilles(noeud: Node) -> int:
    """Nombre de lignes que ce sous-arbre occupe. Au moins une."""
    if not noeud.enfants:
        return 1
    return sum(_feuilles(enfant) for enfant in noeud.enfants)

def _place(
    noeud: Node, profondeur: int, haut: int, places: list[Slot], parent: str
) -> None:
    height = _feuilles(noeud)
    y = (haut + height / 2 - 0.5) * ENTRE_LIGNES
    places.append(Slot(noeud, profondeur * ENTRE_COLONNES, int(y), parent))
    cursor = haut
    for enfant in noeud.enfants:
        _place(enfant, profondeur + 1, cursor, places, noeud.text)
        cursor += _feuilles(enfant)
