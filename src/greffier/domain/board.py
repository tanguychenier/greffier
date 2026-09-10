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

    ACTE = "acté"
    EN_DISCUSSION = "en discussion"
    DEPASSE = "dépassé"

class Kind(StrEnum):
    SUBJECT = "sujet"
    PROBLEME = "problème"
    PISTE = "piste"
    ACTION = "action"
    CONSTAT = "constat"

def content_words(text: str) -> list[str]:
    """The words that carry meaning, **in order**, without accents."""
    nu = unicodedata.normalize("NFKD", text.casefold())
    nu = "".join(lettre for lettre in nu if not unicodedata.combining(lettre))
    tous = [mot for mot in re.split(r"[^a-z0-9]+", nu) if mot]
    carriers = [mot for mot in tous if mot not in _VIDES]
    return carriers or tous

def key(text: str) -> str:
    """What identifies two wordings of the same point."""
    carriers = content_words(text)
    return " ".join(sorted(carriers))

_VIDES = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "au", "aux",
    "et", "ou", "a", "en", "sur", "pour", "par", "avec", "sans", "dans",
    "que", "qui", "se", "ce", "cette", "il", "elle", "on", "est", "sont",
})

GENRES_DECIDABLES = frozenset({Kind.PISTE, Kind.ACTION})

SANS_ETAT = frozenset({Kind.SUBJECT})

def state_allows(kind: Kind, state: Standing) -> Standing:
    """The standing this kind may carry. Falls back to under discussion."""
    if kind in SANS_ETAT:
        return state
    if state is Standing.ACTE and kind not in GENRES_DECIDABLES:
        return Standing.EN_DISCUSSION
    return state

PART_COMMUNE = 0.6

ECART_MOT = 2

LONGUEUR_COMPARABLE = 5

def _near_ones(un: str, autre: str) -> bool:
    """Do two words name the same thing, give or take an ending?"""
    if un == autre:
        return True
    if len(un) < LONGUEUR_COMPARABLE or len(autre) < LONGUEUR_COMPARABLE:
        return False
    from greffier.domain.questions import distance

    return distance(un, autre) <= ECART_MOT

def same_point(un: str, autre: str) -> bool:
    """True when these two labels name the same point of the board."""
    mots_un, mots_autre = set(content_words(un)), set(content_words(autre))
    if not mots_un or not mots_autre:
        return False
    if mots_un == mots_autre:
        return True
    communs = sum(
        1 for mot in mots_un if any(_near_ones(mot, target) for target in mots_autre)
    )
    return communs / max(len(mots_un), len(mots_autre)) >= PART_COMMUNE

@dataclass
class Node:
    """A point of the board, and what hangs off it."""

    text: str
    kind: Kind = Kind.CONSTAT
    state: Standing = Standing.EN_DISCUSSION

    def __post_init__(self) -> None:
        self.state = state_allows(self.kind, self.state)
    enfants: list[Node] = field(default_factory=list)
    meetings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return key(self.text)

    def enfant(self, text: str) -> Node | None:
        """The child that carries this point, rewording aside."""
        return next((n for n in self.enfants if same_point(n.text, text)), None)

    def count(self) -> int:
        """Number of nodes, this one included."""
        return 1 + sum(enfant.count() for enfant in self.enfants)

@dataclass
class Board:
    """A subject's board, as it stands at one instant."""

    subject: str
    racine: Node | None = None

    def __post_init__(self) -> None:
        if self.racine is None:
            self.racine = Node(self.subject, kind=Kind.SUBJECT, state=Standing.ACTE)

    @property
    def count(self) -> int:
        return self.racine.count() if self.racine else 0

@dataclass(frozen=True, slots=True)
class Contribution:
    """What a meeting brings: a point, and where to hang it."""

    text: str
    kind: Kind = Kind.CONSTAT
    state: Standing = Standing.EN_DISCUSSION
    sous: str = ""

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
    assert board.racine is not None
    ajoutes: list[str] = []
    actes: list[str] = []
    known: list[str] = []

    for contribution in apports:
        if not contribution.text.strip():
            continue
        parent = _find(board.racine, contribution.sous) if contribution.sous else board.racine
        if parent is None:
            parent = board.racine
        existant = parent.enfant(contribution.text)
        if existant is None:
            parent.enfants.append(Node(
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
        if voulu is Standing.ACTE and existant.state is Standing.EN_DISCUSSION:
            existant.state = Standing.ACTE
            actes.append(existant.text)
        else:
            known.append(existant.text)

    return Summary(tuple(ajoutes), tuple(actes), tuple(known))

def _find(noeud: Node, text: str) -> Node | None:
    """The node carrying this label, wherever it sits in the tree."""
    if same_point(noeud.text, text):
        return noeud
    for enfant in noeud.enfants:
        trouve = _find(enfant, text)
        if trouve is not None:
            return trouve
    return None

def mark_overdue(board: Board, text: str) -> bool:
    """Marks a point as overdue. The node stays on the board."""
    assert board.racine is not None
    trouve = _find(board.racine, text)
    if trouve is None or trouve is board.racine:
        return False
    trouve.state = Standing.DEPASSE
    return True
