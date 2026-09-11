"""When the assistant speaks in the meeting, and when it keeps quiet.

The hard half is the silence. Being useful is a matter of picking the right
opening; being bearable is a matter of refusing every other one. The refusals
live here, in one place, so that they can be measured rather than argued about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz.distance import Levenshtein

MINIMUM_LULL = 2.0

REST = 180.0

STALENESS = 90.0

MAXIMUM_DENSITY = 0.85

class Because(StrEnum):
    """Why the assistant would want to speak, strongest reason first."""

    APPELE = "on l'appelle"
    INDISTINCT_VOICE = "il ne distingue pas une voix"
    DECISION_WITHOUT_FOLLOW_UP = "une décision sans responsable ni date"
    QUESTION_WITHOUT_ANSWER = "une question restée en l'air"
    GAP_WITH_A_DOCUMENT = "un écart avec un document fourni"
    CONTRIBUTION = "il a quelque chose à ajouter"

WEIGHT = {
    Because.APPELE: 100,
    Because.INDISTINCT_VOICE: 60,
    Because.DECISION_WITHOUT_FOLLOW_UP: 50,
    Because.QUESTION_WITHOUT_ANSWER: 40,
    Because.GAP_WITH_A_DOCUMENT: 30,
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

    creux_minimal: float = MINIMUM_LULL
    rest: float = REST
    staleness: float = STALENESS
    densite_maximale: float = MAXIMUM_DENSITY
    active: bool = True
    spoke_at: float | None = None
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
        if self.spoke_at is not None and now - self.spoke_at < self.rest:
            remaining = self.rest - (now - self.spoke_at)
            return f"il vient de parler, encore {remaining:.0f} s de repos"
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
        self.spoke_at = now
        if opening.subject:
            self.dits.add(opening.subject)

def speech_density(turns: list[tuple[float, float]], now: float,
                      window: float = 60.0) -> float:
    """Share of the last minute in which someone was speaking, 0 to 1."""
    since = max(0.0, now - window)
    width = now - since
    if width <= 0:
        return 0.0
    is_speaking = sum(
        max(0.0, min(end, now) - max(start, since))
        for start, end in turns
    )
    return min(1.0, is_speaking / width)

def _ecart_tolere(name: str) -> int:
    return 1 if len(name) < 5 else 2

def _distance(one: str, other: str, plafond: int) -> int:
    """Edit distance, given up as soon as it passes the ceiling."""
    return int(Levenshtein.distance(one, other, score_cutoff=plafond))

def _strip_accents(word: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", word.lower())
        if unicodedata.category(c) != "Mn"
    )

def called_by_name(text: str, name: str) -> bool:
    """Is the assistant named in this sentence?"""
    cherche = _strip_accents(name.strip())
    if not cherche:
        return False
    plafond = _ecart_tolere(cherche)
    words = re.findall(r"\w+", _strip_accents(text), flags=re.UNICODE)
    return any(_distance(word, cherche, plafond) <= plafond for word in words)

def question_asked(text: str, name: str) -> str:
    """What is being asked of the assistant, with its name removed."""
    cherche = _strip_accents(name.strip())
    plafond = _ecart_tolere(cherche)
    gardes = [
        word for word in re.split(r"(\W+)", text, flags=re.UNICODE)
        if not (word.strip() and _distance(_strip_accents(word), cherche, plafond) <= plafond)
    ]
    remaining = re.sub(r"\s+", " ", "".join(gardes))
    remaining = re.sub(r"\s+([,.])", r"\1", remaining)
    return re.sub(r"^[\s,.:;!?]+", "", remaining).strip()


WORDS_TO_JUDGE = 3
"""Significant words below which an utterance cannot be recognised as its own.

"Oui" and "d'accord" belong to everybody. Deciding on two words would silence
the room every time the assistant had said one of them.
"""

SHARE_OF_WORDS = 0.6
"""Share of an utterance's words that must come from its own remark.

Not all of them: the loudspeakers, the room and the capture loop cost words on
the way, so what comes back is a subset, sometimes a mangled one. Measured on
the assistant's own sentences played through a room, six words in ten survive.
"""

MEMORY_OF_ITS_WORDS = 180.0
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
        _strip_accents(word)
        for word in re.findall(r"\w{4,}", remark, flags=re.UNICODE)
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
    if len(words) < WORDS_TO_JUDGE:
        return False
    return any(
        len(words & dites) >= SHARE_OF_WORDS * len(words)
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
        word for word in re.split(r"(\W+)", remark, flags=re.UNICODE)
        if not (word.strip()
                and _distance(_strip_accents(word), cherche, plafond) <= plafond)
    ]
    remaining = "".join(gardes)
    if remaining == remark:
        return remark
    remaining = re.sub(r"\s+", " ", remaining)
    # La virgule et le point seuls : le français garde une espace avant les
    # deux-points, le point-virgule, le point d'exclamation et d'interrogation.
    remaining = re.sub(r"\s+([,.])", r"\1", remaining)
    return re.sub(r"^[\s,.:;!?]+", "", remaining).strip()
