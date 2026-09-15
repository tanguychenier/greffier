"""Taking a first name out of a text, however that text spells it.

Forgetting somebody is not erasing the meeting they attended: what was decided
around that table belongs to everyone who was there, and the recording of a
meeting is not one person's to withdraw. What has to go is the name and the
voiceprint, everywhere they were written, and what stays is a meeting that
somebody unnamed took part in.

Two things make this harder than a `str.replace`. A name is written with the
accents of whoever typed it -- « Elodie » in the bank, « Élodie » in the
minutes, and macOS writes that accent as two characters where Linux writes one.
And a name is a word: replacing « Luc » must not touch « Lucie », nor the
« luc » inside « caduc ».
"""

from __future__ import annotations

import re
import unicodedata

UNNAMED = "Indéterminé"
"""What replaces the name in a text that keeps its shape.

The same word the window already shows for a voice nobody has named: after an
erasure that is exactly what the voice is again. A minute that read « Élodie
prend la recette » becomes « Indéterminé prend la recette », which keeps the
decision and its owner's turn, and loses the person.
"""

_MARKS = "̀-ͯ"
"""The combining accents, which NFD writes after the letter they sit on."""


def without_marks(text: str) -> str:
    """The text with its accents dropped, for comparing two spellings."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _loose(name: str) -> str:
    """A pattern matching this name whatever accents and spacing it carries."""
    return "".join(
        r"\s+" if character.isspace() else re.escape(character) + f"[{_MARKS}]*"
        for character in without_marks(name)
    )


def pattern_for(name: str) -> re.Pattern[str]:
    """Where a name stands as a word, in a text decomposed to NFD.

    The bounds are `\\w` rather than `\\b`: a name ends before a comma and
    before a full stop, and never in the middle of another word.
    """
    return re.compile(rf"(?<!\w){_loose(name)}(?!\w)", re.IGNORECASE)


def count(text: str, name: str) -> int:
    """How many times this name stands in this text."""
    if not name.strip():
        return 0
    return len(pattern_for(name).findall(unicodedata.normalize("NFD", text)))


def redact(text: str, name: str, replacement: str = UNNAMED) -> tuple[str, int]:
    """The text with every occurrence of the name replaced, and how many.

    A text holding nothing comes back untouched, character for character: the
    normalisation this does to compare spellings would otherwise rewrite files
    that have nothing to do with the person being forgotten.
    """
    if not name.strip():
        return text, 0
    redacted, how_many = pattern_for(name).subn(
        lambda _: replacement, unicodedata.normalize("NFD", text)
    )
    if not how_many:
        return text, 0
    return unicodedata.normalize("NFC", redacted), how_many


def same_person(one: str, other: str) -> bool:
    """Whether two spellings name the same person."""
    return without_marks(one).casefold().strip() == without_marks(other).casefold().strip()
