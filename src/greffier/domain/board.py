"""A subject's board: the problem, the leads, what is settled.

Built from sticky notes and connectors rather than a mindmap widget: the widget
is a third-party app whose nodes the REST API can neither create nor read, and
reading back is what allows a board to be completed instead of duplicated.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum


class Standing(StrEnum):
    """What the board asserts about a node."""

    AGREED = "acté"
    UNDER_DISCUSSION = "en discussion"
    OVERTAKEN = "dépassé"

class Kind(StrEnum):
    SUBJECT = "sujet"
    PROBLEM = "problème"
    LEAD = "piste"
    ACTION = "action"
    OBSERVATION = "constat"

def content_words(text: str) -> list[str]:
    """The words that carry meaning, **in order**, without accents."""
    nu = unicodedata.normalize("NFKD", text.casefold())
    nu = "".join(lettre for lettre in nu if not unicodedata.combining(lettre))
    all_of_them = [word for word in re.split(r"[^a-z0-9]+", nu) if word]
    carriers = [word for word in all_of_them if word not in _EMPTY]
    return carriers or all_of_them

def key(text: str) -> str:
    """What identifies two wordings of the same point."""
    carriers = content_words(text)
    return " ".join(sorted(carriers))

_EMPTY = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "au", "aux",
    "et", "ou", "a", "en", "sur", "pour", "par", "avec", "sans", "dans",
    "que", "qui", "se", "ce", "cette", "il", "elle", "on", "est", "sont",
})

DECIDABLE_KINDS = frozenset({Kind.LEAD, Kind.ACTION})

WITHOUT_STANDING = frozenset({Kind.SUBJECT})

def state_allows(kind: Kind, state: Standing) -> Standing:
    """The standing this kind may carry. Falls back to under discussion."""
    if kind in WITHOUT_STANDING:
        return state
    if state is Standing.AGREED and kind not in DECIDABLE_KINDS:
        return Standing.UNDER_DISCUSSION
    return state

COMMON_SHARE = 0.6

WORD_GAP = 2

COMPARABLE_LENGTH = 5

def _near_ones(one: str, other: str) -> bool:
    """Do two words name the same thing, give or take an ending?"""
    if one == other:
        return True
    if len(one) < COMPARABLE_LENGTH or len(other) < COMPARABLE_LENGTH:
        return False
    from greffier.domain.questions import distance

    return distance(one, other) <= WORD_GAP

def same_point(one: str, other: str) -> bool:
    """True when these two labels name the same point of the board."""
    one_words, other_words = set(content_words(one)), set(content_words(other))
    if not one_words or not other_words:
        return False
    if one_words == other_words:
        return True
    communs = sum(
        1 for word in one_words if any(_near_ones(word, target) for target in other_words)
    )
    return communs / max(len(one_words), len(other_words)) >= COMMON_SHARE

@dataclass
class Node:
    """A point of the board, and what hangs off it."""

    text: str
    kind: Kind = Kind.OBSERVATION
    state: Standing = Standing.UNDER_DISCUSSION

    def __post_init__(self) -> None:
        self.state = state_allows(self.kind, self.state)
    children: list[Node] = field(default_factory=list)
    meetings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return key(self.text)

    def enfant(self, text: str) -> Node | None:
        """The child that carries this point, rewording aside."""
        return next((n for n in self.children if same_point(n.text, text)), None)

    def count(self) -> int:
        """Number of nodes, this one included."""
        return 1 + sum(enfant.count() for enfant in self.children)

@dataclass
class Board:
    """A subject's board, as it stands at one instant."""

    subject: str
    root: Node | None = None

    def __post_init__(self) -> None:
        if self.root is None:
            self.root = Node(self.subject, kind=Kind.SUBJECT, state=Standing.AGREED)

    @property
    def count(self) -> int:
        return self.root.count() if self.root else 0

@dataclass(frozen=True, slots=True)
class Contribution:
    """What a meeting brings: a point, and where to hang it."""

    text: str
    kind: Kind = Kind.OBSERVATION
    state: Standing = Standing.UNDER_DISCUSSION
    under: str = ""

@dataclass(frozen=True, slots=True)
class Summary:
    """What a join changed. Nothing is ever deleted."""

    ajoutes: tuple[str, ...] = ()
    actes: tuple[str, ...] = ()
    known: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.ajoutes and not self.actes

def join(board: Board, apports: list[Contribution], meeting: str = "") -> Summary:
    """Pours the contributions into the board. **Never erases anything.**"""
    assert board.root is not None
    ajoutes: list[str] = []
    actes: list[str] = []
    known: list[str] = []

    for contribution in apports:
        if not contribution.text.strip():
            continue
        parent = _find(board.root, contribution.under) if contribution.under else board.root
        if parent is None:
            parent = board.root
        existant = parent.enfant(contribution.text)
        if existant is None:
            parent.children.append(Node(
                text=contribution.text.strip(),
                kind=contribution.kind,
                state=contribution.state,
                meetings=[meeting] if meeting else [],
            ))
            ajoutes.append(contribution.text.strip())
            continue
        if meeting and meeting not in existant.meetings:
            existant.meetings.append(meeting)
        voulu = state_allows(existant.kind, contribution.state)
        if voulu is Standing.AGREED and existant.state is Standing.UNDER_DISCUSSION:
            existant.state = Standing.AGREED
            actes.append(existant.text)
        else:
            known.append(existant.text)

    return Summary(tuple(ajoutes), tuple(actes), tuple(known))

def _find(noeud: Node, text: str) -> Node | None:
    """The node carrying this label, wherever it sits in the tree."""
    if same_point(noeud.text, text):
        return noeud
    for enfant in noeud.children:
        found = _find(enfant, text)
        if found is not None:
            return found
    return None

def mark_overdue(board: Board, text: str) -> bool:
    """Marks a point as overdue. The node stays on the board."""
    assert board.root is not None
    found = _find(board.root, text)
    if found is None or found is board.root:
        return False
    found.state = Standing.OVERTAKEN
    return True
