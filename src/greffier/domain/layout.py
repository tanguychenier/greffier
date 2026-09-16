"""Where to place a board's nodes on a plane."""

from __future__ import annotations

from dataclasses import dataclass

from greffier.domain.board import Board, Node

WIDTH = 220
BETWEEN_COLUMNS = 380

BETWEEN_LINES = 170

@dataclass(frozen=True, slots=True)
class Slot:
    """A node and the place it goes."""

    node: Node
    x: int
    y: int
    parent: str = ""

def lay_out(board: Board) -> list[Slot]:
    """The slots of every node, root included."""
    if board.root is None:
        return []
    places: list[Slot] = []
    _place(board.root, depth=0, top=0, places=places, parent="")
    return places

def _leaves(node: Node) -> int:
    """Number of rows this subtree occupies. At least one."""
    if not node.children:
        return 1
    return sum(_leaves(child) for child in node.children)

def _place(
    node: Node, depth: int, top: int, places: list[Slot], parent: str
) -> None:
    height = _leaves(node)
    y = (top + height / 2 - 0.5) * BETWEEN_LINES
    places.append(Slot(node, depth * BETWEEN_COLUMNS, int(y), parent))
    cursor = top
    for child in node.children:
        _place(child, depth + 1, cursor, places, node.text)
        cursor += _leaves(child)
