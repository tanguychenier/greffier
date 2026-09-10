"""A meeting's language, and what it changes in the domain.

Gathered in one object the domain receives, rather than scattered through it:
that is what makes the rules testable in a language nobody here speaks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from greffier.domain.models import MentionKind

Reason = tuple[MentionKind, "re.Pattern[str]", bool]

@dataclass(frozen=True, slots=True)
class Detection:
    """How to recognise a spoken first name, in a given language."""

    active: bool
    motifs: tuple[Reason, ...] = ()
    exclus: frozenset[str] = frozenset()
    longueur_minimale: int = 3
    suffixe_adverbial: str = ""
    longueur_du_suffixe: int = 0

@dataclass(frozen=True, slots=True)
class Splitting:
    """How this language separates its words."""

    mots_separes_par_des_espaces: bool = True

    def count_them(self, text: str) -> int:
        """The number of words, or of characters where words do not apply."""
        if self.mots_separes_par_des_espaces:
            return len(text.split())
        return len(text.replace(" ", ""))

@dataclass(frozen=True, slots=True)
class Wording:
    """What the language changes in how what was said is read back."""

    boilerplate: frozenset[str] = frozenset()
    motifs_de_decision: tuple[re.Pattern[str], ...] = ()

@dataclass(frozen=True, slots=True)
class LanguageProfile:
    """Everything a language decides, in one object."""

    code: str
    name: str
    detection: Detection
    decoupage: Splitting = field(default_factory=Splitting)
    redaction: Wording = field(default_factory=Wording)

    @property
    def eprouve(self) -> bool:
        """Whether this profile can recognise first names in its language."""
        return self.detection.active
