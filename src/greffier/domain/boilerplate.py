"""Discards the boilerplate the transcription model invents on silence.

"Thanks for watching this video" and its kin come from the training data, not
from the room.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from greffier.domain.language import LanguageProfile
from greffier.domain.models import Span, Utterance

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
    return _nu(text) in profil.wording.boilerplate

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



REPEATS_THAT_ARE_A_LOOP = 3
"""How many identical utterances in a row make it a transcription loop.

Two identical sentences in a row happen: someone repeats themselves, or the
slices overlap. Three or more, each abutting the next with no gap, do not.

Measured on the meeting of 2026-09-10: "Est-ce que tu entends Lucie ?"
appeared **eleven times**, in eleven consecutive one-second turns. Whisper does
that on near-silence, and the thread inscribed every one of them.
"""

LOOP_GAP = 0.35
"""Seconds of silence beyond which two identical sentences are two sentences.

Someone repeating a question leaves a breath. A model looping does not.
"""


def collapse_loops(
    utterances: list[Utterance], repeats: int = REPEATS_THAT_ARE_A_LOOP,
    gap: float = LOOP_GAP,
) -> list[Utterance]:
    """Reduces a transcription loop to the one sentence that was said.

    Keeps the first of the run and stretches it over the whole run, so that the
    timing stays honest: the passage really did last eleven seconds, whatever
    the model made of it.

    Two identical sentences in a row are left alone — that is a person.
    """
    if len(utterances) < repeats:
        return list(utterances)
    output: list[Utterance] = []
    i = 0
    while i < len(utterances):
        j = i + 1
        while (
            j < len(utterances)
            and _nu(utterances[j].text) == _nu(utterances[i].text)
            and utterances[j].span.start - utterances[j - 1].span.end <= gap
        ):
            j += 1
        how_many = j - i
        if how_many >= repeats:
            output.append(replace(
                utterances[i],
                span=Span(utterances[i].span.start, utterances[j - 1].span.end),
            ))
        else:
            output.extend(utterances[i:j])
        i = j
    return output
