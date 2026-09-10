"""Where to place a board's nodes on a plane."""

from __future__ import annotations

from dataclasses import dataclass

from greffier.domain.board import Board, Node

WIDTH = 220
ENTRE_COLONNES = 380

ENTRE_LIGNES = 170

@dataclass(frozen=True, slots=True)
class Slot:
    """A node and the place it goes."""

    noeud: Node
    x: int
    y: int
    parent: str = ""

def disposer(board: Board) -> list[Slot]:
    """The slots of every node, root included."""
    if board.racine is None:
        return []
    places: list[Slot] = []
    _place(board.racine, profondeur=0, haut=0, places=places, parent="")
    return places

def _feuilles(noeud: Node) -> int:
    """Number of rows this subtree occupies. At least one."""
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
