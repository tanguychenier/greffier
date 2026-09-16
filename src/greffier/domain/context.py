"""What the tool knows of the setting a meeting takes place in.

Acronyms, products, people: what no model can guess and what improves rare
proper nouns more than anything else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

PROMPT_MAXIMUM = 850

_PREAMBLE = "Réunion de travail."

@dataclass(frozen=True, slots=True)
class Term:
    """A word the model cannot guess: acronym, product, proper noun."""

    spelling: str
    meaning: str = ""

    def __post_init__(self) -> None:
        if not self.spelling.strip():
            raise ValueError("un terme sans écriture ne sert à rien")

    @property
    def gloss(self) -> str:
        """"OTP (one-time password)", or just "OTP" when the sense is unknown."""
        return f"{self.spelling} ({self.meaning})" if self.meaning else self.spelling

@dataclass(frozen=True, slots=True)
class Speaker_:
    """Someone whose name is spoken in meetings."""

    name: str
    role: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("un intervenant sans nom ne sert à rien")

    @property
    def gloss(self) -> str:
        return f"{self.name} ({self.role})" if self.role else self.name

@dataclass(frozen=True, slots=True)
class Context:
    """The glossary and the directory of a working setting."""

    terms: tuple[Term, ...] = ()
    attendees_: tuple[Speaker_, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.terms and not self.attendees_

    def join(self, other: Context) -> Context:
        """This context, completed by another, which wins on equal names."""
        terms = {t.spelling.casefold(): t for t in self.terms}
        terms.update({t.spelling.casefold(): t for t in other.terms})
        gens = {i.name.casefold(): i for i in self.attendees_}
        gens.update({i.name.casefold(): i for i in other.attendees_})
        return Context(tuple(terms.values()), tuple(gens.values()))

    def prompt_seed(self, heard_before: Sequence[str] = ()) -> str:
        """The transcriber's seed: spellings, without their meaning.

        Measured on a meeting carrying seven rare terms: eleven of the fifteen
        occurrences come back without this seed, fifteen out of fifteen with it.
        « backlog » became « bâcle », « Kanban » became « cambans ».

        The people expected at a meeting come last and cost nothing to add:
        they were named before the meeting, they have no voice in the bank yet,
        and a first name is exactly the kind of rare word a model replaces with
        something it knows.
        """
        retained_ones = _hold(self._words(heard_before),
                        PROMPT_MAXIMUM - len(_PREAMBLE) - len(" Vocabulaire : ."))
        if not retained_ones:
            return ""
        return f"{_PREAMBLE} Vocabulaire : " + ", ".join(retained_ones) + "."

    def set_aside(self, heard_before: Sequence[str] = ()) -> tuple[str, ...]:
        """The terms the seed could not carry, so that it can be said."""
        words = self._words(heard_before)
        retained_ones = set(_hold(words, PROMPT_MAXIMUM - len(_PREAMBLE) - len(" Vocabulaire : .")))
        return tuple(m for m in words if m not in retained_ones)

    def _words(self, heard_before: Sequence[str] = ()) -> list[str]:
        """What the seed may carry, in the order it gives up.

        The glossary and the declared people first, since somebody wrote them
        down on purpose; those merely expected last, since a preparation lists
        a room and would otherwise push out what was chosen for good.
        """
        return ([t.spelling for t in self.terms]
                + [i.name for i in self.attendees_]
                + [name for name in heard_before if name.strip()])

    def header(self) -> str:
        """The glossary dictated to the writer, meanings included."""
        if self.empty:
            return ""
        lines = ["[Contexte du milieu de travail]"]
        if self.terms:
            lines.append(
                "Termes et sigles employés dans cette organisation, avec leur sens. "
                "Emploie ces écritures, y compris là où la transcription les a "
                "manifestement déformés. N'en cite que ceux dont il est question :"
            )
            lines += [f"- {t.gloss}" for t in self.terms]
        if self.attendees_:
            lines.append(
                "Personnes de cette organisation. N'attribue une position à "
                "quelqu'un que si la transcription le montre, jamais d'après son rôle :"
            )
            lines += [f"- {i.gloss}" for i in self.attendees_]
        return "\n".join(lines) + "\n\n"

def _hold(words: list[str], place: int) -> list[str]:
    """The first words that fit in the room available."""
    retained_ones: list[str] = []
    length = 0
    for word in dict.fromkeys(m for m in words if m.strip()):
        addition = len(word) + (2 if retained_ones else 0)
        if length + addition > place:
            continue
        retained_ones.append(word)
        length += addition
    return retained_ones
