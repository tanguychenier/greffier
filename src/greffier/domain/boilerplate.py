"""Discards the boilerplate the transcription model invents on silence.

"Thanks for watching this video" and its kin come from the training data, not
from the room.
"""

from __future__ import annotations

import re
import unicodedata

from greffier.domain.language import LanguageProfile

_PONCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_ESPACES = re.compile(r"\s+")

def _nu(text: str) -> str:
    """The text without accents, without punctuation, in lower case."""
    strip_accents = "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )
    return _ESPACES.sub(" ", _PONCTUATION.sub(" ", strip_accents)).strip()

def is_boilerplate(text: str, profil: LanguageProfile) -> bool:
    """True when the whole utterance is boilerplate from the model."""
    return _nu(text) in profil.redaction.boilerplate

_BORNES_ANNOTATION = (("*", "*"), ("(", ")"), ("[", "]"), ("♪", "♪"), ("{", "}"))

def is_an_annotation(text: str) -> bool:
    """True when the whole utterance is an annotation, not speech."""
    nu = text.strip()
    if len(nu) < 3:
        return False
    for ouvre, firm in _BORNES_ANNOTATION:
        if not (nu.startswith(ouvre) and nu.endswith(firm)):
            continue
        if ouvre != firm:
            return firm not in nu[len(ouvre):-len(firm)]
        return nu.count(ouvre) == 2 or not nu.replace(ouvre, "").strip()
    return False

