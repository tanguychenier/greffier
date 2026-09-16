"""Cutting what the model says, as it says it, at the sentences it has finished.

The answer arrives word by word; the voice wants whole sentences. What
comes out of here is what can be spoken already, and what has to wait for
the next words: a full stop is the end of a sentence only once something
follows it, since « 3. » may be the start of « 3.5 ».
"""

from __future__ import annotations

import re

SENTENCE_ENDS = re.compile(r"(?<=[.!?…])\s+")


class SentencesAsTheyCome:
    """Holds the words not yet spoken, and hands out the finished sentences."""

    def __init__(self) -> None:
        self.pending = ""

    def take(self, words: str) -> list[str]:
        """Adds words; returns the sentences those words have completed."""
        self.pending += words
        pieces = SENTENCE_ENDS.split(self.pending)
        if len(pieces) < 2:
            return []
        self.pending = pieces[-1]
        return [piece.strip() for piece in pieces[:-1] if piece.strip()]

    def finish(self) -> list[str]:
        """The end of the answer: whatever is left is a sentence too."""
        last, self.pending = self.pending.strip(), ""
        return [last] if last else []
