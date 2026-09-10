"""What the tool does not understand, and may ask about.

A question costs the room's attention, so the bar is high: it asks only about
what recurs, never twice about the same thing, and never about a word it has
already seen written correctly. Measured on 3 765 real utterances: 8 questions
became 3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

LONGUEUR_TOLERANCE_LARGE = 8
DISTANCE_MAXIMUM = 2

LONGUEUR_MINIMALE = 5

def tolerance(terme: str) -> int:
    """How many differences are accepted before believing in a distortion."""
    return DISTANCE_MAXIMUM if len(terme) >= LONGUEUR_TOLERANCE_LARGE else 1

QUESTIONS_MAXIMUM = 8

OCCURRENCES_QUI_ETABLISSENT = 2

_MOT = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)

_PLURIEL = re.compile(r"(?:s|x)$")

def canonical_form(mot: str) -> str:
    """What is left of a word once what does not change it is removed."""
    import unicodedata

    depouille = unicodedata.normalize("NFD", mot.casefold())
    without_accents = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    sans_liaison = re.sub(r"[-'’\s]", "", without_accents)
    return _PLURIEL.sub("", sans_liaison)

def same_word(un: str, autre: str) -> bool:
    """Do the two differ only by plural, accent or case?"""
    return canonical_form(un) == canonical_form(autre)

PREFIXES = ("re", "ré", "de", "dé", "in", "im", "non", "anti", "pre", "pré",
            "sur", "sous", "mal", "co")

def derived_word(mot: str, terme: str) -> bool:
    """Is the word the term with a French prefix in front of it?"""
    court, long = canonical_form(terme), canonical_form(mot)
    if len(long) <= len(court) or not court:
        return False
    for prefixe in (canonical_form(p) for p in PREFIXES):
        if not long.startswith(prefixe):
            continue
        reste = long[len(prefixe):]
        if reste == court or (court[0] in "aeiouy" and reste == court[1:]):
            return True
    return False

class Motif(StrEnum):
    """Why the tool is asking. Shown on screen: a question without a reason
    reads as noise.
    """

    NEAR_TERM = "terme-proche"

@dataclass(frozen=True, slots=True)
class Question:
    number: int
    text: str
    motif: Motif
    entendu: str = ""
    attendu: str = ""

    @property
    def key(self) -> str:
        """What identifies an already asked question, without leaning on the text."""
        return f"{self.motif}:{self.entendu.casefold()}:{self.attendu.casefold()}"

def distance(un: str, autre: str) -> int:
    """Edit distance **with transposition** (Damerau-Levenshtein)."""
    if un == autre:
        return 0
    if abs(len(un) - len(autre)) > DISTANCE_MAXIMUM:
        return DISTANCE_MAXIMUM + 1
    before_previous: list[int] = []
    precedente = list(range(len(autre) + 1))
    for i, lettre_un in enumerate(un, start=1):
        courante = [i]
        for j, lettre_autre in enumerate(autre, start=1):
            cout = min(
                precedente[j] + 1,
                courante[j - 1] + 1,
                precedente[j - 1] + (lettre_un != lettre_autre),
            )
            if (
                i > 1 and j > 1
                and lettre_un == autre[j - 2]
                and un[i - 2] == lettre_autre
            ):
                cout = min(cout, before_previous[j - 2] + 1)
            courante.append(cout)
        before_previous, precedente = precedente, courante
    return precedente[-1]

def _words(text: str) -> list[str]:
    return _MOT.findall(text)

@dataclass
class Questioner:
    """Spots what deserves a question, and never asks the same one twice."""

    known: tuple[str, ...] = ()
    posees: set[str] = field(default_factory=set)
    _entendus: dict[str, int] = field(default_factory=dict, repr=False)
    _number: int = 0

    def __post_init__(self) -> None:
        eclates: list[str] = []
        for terme in self.known:
            eclates.append(terme)
            chunks = _words(terme)
            if len(chunks) > 1:
                eclates.extend(m for m in chunks if len(m) >= LONGUEUR_MINIMALE)
        vus: dict[str, str] = {}
        for terme in eclates:
            vus.setdefault(terme.casefold(), terme)
        self.known = tuple(vus.values())

    def examine(self, text: str) -> list[Question]:
        """The questions this passage raises. Empty most of the time."""
        self._retenir(text)
        if len(self.posees) >= QUESTIONS_MAXIMUM:
            return []
        trouvees: list[Question] = []
        for mot in _words(text):
            if len(mot) < LONGUEUR_MINIMALE:
                continue
            nu = mot.casefold()
            candidat = self._near_term(nu)
            if candidat is None:
                continue
            if self._established(nu) or self._already_said_right(candidat):
                continue
            question = Question(
                number=self._number + 1,
                text=(
                    f"J'ai entendu « {mot} ». Fallait-il comprendre "
                    f"« {candidat} » ?"
                ),
                motif=Motif.NEAR_TERM,
                entendu=mot,
                attendu=candidat,
            )
            if question.key in self.posees:
                continue
            self.posees.add(question.key)
            self._number += 1
            trouvees.append(question)
            if len(self.posees) >= QUESTIONS_MAXIMUM:
                break
        return trouvees

    def _retenir(self, text: str) -> None:
        """Counts what was heard, before judging anything."""
        for mot in _words(text):
            if len(mot) < LONGUEUR_MINIMALE:
                continue
            key = canonical_form(mot)
            self._entendus[key] = self._entendus.get(key, 0) + 1

    def _established(self, mot_nu: str) -> bool:
        """Does this word recur often enough to be a word that was meant?"""
        return self._entendus.get(canonical_form(mot_nu), 0) >= (
            OCCURRENCES_QUI_ETABLISSENT)

    def _already_said_right(self, terme: str) -> bool:
        """Has the expected term already been transcribed correctly?"""
        return canonical_form(terme) in self._entendus

    def _near_term(self, mot_nu: str) -> str | None:
        """The known term this word is probably a distortion of."""
        best: tuple[int, str] | None = None
        for terme in self.known:
            terme_nu = terme.casefold()
            if terme_nu == mot_nu or same_word(mot_nu, terme_nu):
                return None
            if derived_word(mot_nu, terme_nu):
                return None
            if len(terme) < LONGUEUR_MINIMALE:
                continue
            gap = distance(mot_nu, terme_nu)
            if gap <= tolerance(terme) and (best is None or gap < best[0]):
                best = (gap, terme)
        return best[1] if best else None
