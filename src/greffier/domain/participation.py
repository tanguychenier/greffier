"""When the assistant speaks in the meeting, and when it keeps quiet.

The hard half is the silence. Being useful is a matter of picking the right
opening; being bearable is a matter of refusing every other one. The refusals
live here, in one place, so that they can be measured rather than argued about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

CREUX_MINIMAL = 2.0

REST = 180.0

STALENESS = 90.0

DENSITE_MAXIMALE = 0.85

class Because(StrEnum):
    """Why the assistant would want to speak, strongest reason first."""

    APPELE = "on l'appelle"
    VOIX_INDISTINCTE = "il ne distingue pas une voix"
    DECISION_SANS_SUITE = "une décision sans responsable ni date"
    QUESTION_SANS_REPONSE = "une question restée en l'air"
    ECART_AVEC_UN_DOCUMENT = "un écart avec un document fourni"
    CONTRIBUTION = "il a quelque chose à ajouter"

WEIGHT = {
    Because.APPELE: 100,
    Because.VOIX_INDISTINCTE: 60,
    Because.DECISION_SANS_SUITE: 50,
    Because.QUESTION_SANS_REPONSE: 40,
    Because.ECART_AVEC_UN_DOCUMENT: 30,
    Because.CONTRIBUTION: 10,
}

@dataclass(frozen=True, slots=True)
class Opening:
    """Something the assistant could say, and what justifies it."""

    because: Because
    remark: str
    born_at: float = 0.0
    subject: str = ""
    as_is: bool = False

    @property
    def weight(self) -> int:
        return WEIGHT[self.because]

    @property
    def urgent(self) -> bool:
        """An opening that ignores both the rest period and the density."""
        return self.because is Because.APPELE

@dataclass
class Manners:
    """What the assistant allows itself, and the memory of what it said."""

    creux_minimal: float = CREUX_MINIMAL
    rest: float = REST
    staleness: float = STALENESS
    densite_maximale: float = DENSITE_MAXIMALE
    active: bool = True
    parle_le: float | None = None
    dits: set[str] = field(default_factory=set)

    def refusal(
        self,
        opening: Opening,
        now: float,
        lull: float,
        density: float = 0.0,
    ) -> str | None:
        """What stops this opening being said, or nothing if it may be."""
        if not self.active:
            return "il ne participe pas"
        if opening.subject and opening.subject in self.dits:
            return "déjà dit"
        if opening.urgent:
            return None
        if now - opening.born_at > self.staleness:
            return "la conversation est passée à autre chose"
        if lull < self.creux_minimal:
            return "quelqu'un parle"
        if density > self.densite_maximale:
            return "la discussion est trop dense"
        if self.parle_le is not None and now - self.parle_le < self.rest:
            reste = self.rest - (now - self.parle_le)
            return f"il vient de parler, encore {reste:.0f} s de repos"
        return None

    def choose(
        self,
        occasions: list[Opening],
        now: float,
        lull: float,
        density: float = 0.0,
    ) -> Opening | None:
        """At most one opening, the strongest of those that pass."""
        possibles = [
            o for o in occasions
            if self.refusal(o, now, lull, density) is None
        ]
        if not possibles:
            return None
        return max(possibles, key=lambda o: (o.weight, o.born_at))

    def has_spoken(self, opening: Opening, now: float) -> None:
        """To be called once the remark has actually been spoken."""
        self.parle_le = now
        if opening.subject:
            self.dits.add(opening.subject)

def speech_density(turns: list[tuple[float, float]], now: float,
                      window: float = 60.0) -> float:
    """Share of the last minute in which someone was speaking, 0 to 1."""
    depuis = max(0.0, now - window)
    width = now - depuis
    if width <= 0:
        return 0.0
    is_speaking = sum(
        max(0.0, min(end, now) - max(start, depuis))
        for start, end in turns
    )
    return min(1.0, is_speaking / width)

def _ecart_tolere(name: str) -> int:
    return 1 if len(name) < 5 else 2

def _distance(un: str, autre: str, plafond: int) -> int:
    """Edit distance, abandoned as soon as it passes the ceiling."""
    if abs(len(un) - len(autre)) > plafond:
        return plafond + 1
    precedent = list(range(len(autre) + 1))
    for i, lettre in enumerate(un, start=1):
        current = [i]
        for j, autre_lettre in enumerate(autre, start=1):
            current.append(min(
                precedent[j] + 1,
                current[j - 1] + 1,
                precedent[j - 1] + (lettre != autre_lettre),
            ))
        if min(current) > plafond:
            return plafond + 1
        precedent = current
    return precedent[-1]

def _strip_accents(mot: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", mot.lower())
        if unicodedata.category(c) != "Mn"
    )

def called_by_name(text: str, name: str) -> bool:
    """Is the assistant named in this sentence?"""
    cherche = _strip_accents(name.strip())
    if not cherche:
        return False
    plafond = _ecart_tolere(cherche)
    words = re.findall(r"\w+", _strip_accents(text), flags=re.UNICODE)
    return any(_distance(mot, cherche, plafond) <= plafond for mot in words)

def question_asked(text: str, name: str) -> str:
    """What is being asked of the assistant, with its name removed."""
    cherche = _strip_accents(name.strip())
    plafond = _ecart_tolere(cherche)
    gardes = [
        mot for mot in re.split(r"(\W+)", text, flags=re.UNICODE)
        if not (mot.strip() and _distance(_strip_accents(mot), cherche, plafond) <= plafond)
    ]
    reste = re.sub(r"\s+", " ", "".join(gardes))
    reste = re.sub(r"\s+([,.])", r"\1", reste)
    return re.sub(r"^[\s,.:;!?]+", "", reste).strip()
