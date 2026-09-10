"""Recognising which subject a meeting is about, and finding its board."""

from __future__ import annotations

from dataclasses import dataclass, field

from greffier.domain.board import content_words, key

MENTIONS_MINIMALES = 3

@dataclass(frozen=True, slots=True)
class Subject:
    """A tracked subject, its aliases, and where its board lives."""

    name: str
    alias: tuple[str, ...] = ()
    board: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("un sujet sans nom ne se retrouve pas")

    @property
    def forms_of_address(self) -> tuple[str, ...]:
        return (self.name, *self.alias)

    def recognises(self, word: str) -> bool:
        """True when this word is one of its aliases."""
        return key(word) in {key(name) for name in self.forms_of_address}

@dataclass
class Registry:
    """The tracked subjects, and what a transcript says about them."""

    subjects: list[Subject] = field(default_factory=list)

    def by_name(self, name: str) -> Subject | None:
        return next((subject for subject in self.subjects if subject.recognises(name)), None)

    def count_them(self, text: str) -> dict[str, int]:
        """How many times each tracked subject is named in this text."""
        words = content_words(text)
        present: dict[str, int] = {}
        for subject in self.subjects:
            total = _count_without_overlap(words, subject.forms_of_address)
            if total:
                present[subject.name] = total
        return present

    def subjects_of(self, text: str, minimum: int = MENTIONS_MINIMALES) -> list[str]:
        """The subjects actually discussed, most present first."""
        comptes = self.count_them(text)
        retenus = [(name, count) for name, count in comptes.items() if count >= minimum]
        return [name for name, _ in sorted(retenus, key=lambda pair: -pair[1])]

def _count_without_overlap(
    words: list[str], forms_of_address: tuple[str, ...]
) -> int:
    """How many times this subject is named, counting each hit once."""
    suites = sorted(
        (content_words(appellation) for appellation in forms_of_address),
        key=len, reverse=True,
    )
    suites = [suite for suite in suites if suite]
    if not suites:
        return 0
    total = 0
    position = 0
    while position < len(words):
        trouvee = next(
            (suite for suite in suites
             if words[position:position + len(suite)] == suite),
            None,
        )
        if trouvee is None:
            position += 1
            continue
        total += 1
        position += len(trouvee)
    return total
