"""What a meeting's attendees must be able to know.

A voice is biometric data. The minutes carry the matching statement, and the
tool refuses to pretend that was settled when it was not.
"""

from __future__ import annotations

from enum import StrEnum


class Disclosure(StrEnum):
    """What was done towards the attendees."""

    RIEN = "rien"
    ANNONCE = "annoncé"
    AGREEMENT = "accord"

MENTIONS = {
    Disclosure.RIEN: (
        "Cette réunion a été enregistrée et transcrite automatiquement. "
        "L'information des participants n'a pas été tracée."
    ),
    Disclosure.ANNONCE: (
        "Cette réunion a été enregistrée et transcrite automatiquement, "
        "les participants en ayant été informés."
    ),
    Disclosure.AGREEMENT: (
        "Cette réunion a été enregistrée et transcrite automatiquement, "
        "avec l'accord des participants."
    ),
}

RAPPEL = (
    "Une voix est une donnée biométrique. Pense à prévenir les participants "
    "que la réunion est enregistrée — et note-le dans « conversation.information » "
    "pour que le compte rendu le dise."
)

def mention(disclosure: Disclosure) -> str:
    """The sentence to carry into the minutes."""
    return MENTIONS[disclosure]

def to_draw(disclosure: Disclosure) -> bool:
    """True when something is still owed to the attendees."""
    return disclosure is Disclosure.RIEN

def read(brut: str) -> Disclosure:
    """What the configuration says, or "nothing" when it says nothing."""
    nu = brut.strip().casefold()
    for value in Disclosure:
        if nu == str(value).casefold():
            return value
    return Disclosure.RIEN
