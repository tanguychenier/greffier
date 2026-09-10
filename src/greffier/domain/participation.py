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


MOTS_POUR_JUGER = 3
"""Significant words below which an utterance cannot be recognised as its own.

"Oui" and "d'accord" belong to everybody. Deciding on two words would silence
the room every time the assistant had said one of them.
"""

PART_DES_MOTS = 0.6
"""Share of an utterance's words that must come from its own remark.

Not all of them: the loudspeakers, the room and the capture loop cost words on
the way, so what comes back is a subset, sometimes a mangled one. Measured on
the assistant's own sentences played through a room, six words in ten survive.
"""

MEMOIRE_DE_SES_MOTS = 180.0
"""Seconds a remark stays recognisable as its own.

Long, on purpose. It answers late — the model takes seconds, the voice takes
more — and its words can come back several slices later. Shorter, the loop
starts again; there is no cost to remembering.
"""


def own_words(remark: str) -> frozenset[str]:
    """The significant words of a remark, for recognising it when it returns.

    Accents and case removed, short words dropped: what comes back through the
    loudspeakers and the capture loop is never spelt the same way.
    """
    return frozenset(
        _strip_accents(mot)
        for mot in re.findall(r"\w{4,}", remark, flags=re.UNICODE)
    )


def is_own(text: str, remarks: list[frozenset[str]]) -> bool:
    """Is this utterance the assistant hearing itself?

    The defect this answers: it speaks through the loudspeakers, the tool
    records the system output on purpose — that is how it hears the other
    people in a video call — so its own voice comes back on the channel meant
    for everybody else. It then reads its own name in its own answer and
    answers again, **for ever**.

    Judged on the words and not on the clock, and that is the whole point: it
    answers late, in a separate thread, so no window of time can be trusted.
    """
    words = own_words(text)
    if len(words) < MOTS_POUR_JUGER:
        return False
    return any(
        len(words & dites) >= PART_DES_MOTS * len(words)
        for dites in remarks
        if dites
    )


def without_own_name(remark: str, name: str) -> str:
    """The remark with the assistant's own name taken out.

    Its own name must never leave its mouth, and that is a hard guarantee
    rather than a precaution: it speaks through the loudspeakers, the tool
    records the system output on purpose, so whatever it says comes back
    transcribed. A remark carrying its own name calls it again, and it answers
    again — **for ever**. Observed in a real meeting, fifteen times in fifteen
    seconds.
    """
    cherche = _strip_accents(name.strip())
    if not cherche:
        return remark
    plafond = _ecart_tolere(cherche)
    gardes = [
        mot for mot in re.split(r"(\W+)", remark, flags=re.UNICODE)
        if not (mot.strip()
                and _distance(_strip_accents(mot), cherche, plafond) <= plafond)
    ]
    reste = "".join(gardes)
    if reste == remark:
        return remark
    reste = re.sub(r"\s+", " ", reste)
    # La virgule et le point seuls : le français garde une espace avant les
    # deux-points, le point-virgule, le point d'exclamation et d'interrogation.
    reste = re.sub(r"\s+([,.])", r"\1", reste)
    return re.sub(r"^[\s,.:;!?]+", "", reste).strip()
