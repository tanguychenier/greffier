"""What the transcription model produces when it loses the thread.

It repeats. Given ten seconds of muddy audio it writes the same clause over and
over until the slice runs out, and the sentence lands in the minutes as it is.
Measured on 3 797 turns of real meetings: 23 of them loop, the worst being the
same eight words eighteen times in a row, 608 characters for ten seconds of
speech.
"""

from __future__ import annotations

import re

REPEATS_ALLOWED = 2
"""How many times in a row a clause may be said before it is a loop.

Two, not one: people do repeat themselves for emphasis, *c'est vrai, c'est
vrai*, and cutting that would rewrite what was said. Measured, the loops run
from four times up, so nothing real is touched.
"""

SHORTEST_LOOP = 1

LONGEST_LOOP = 12
"""Words in the longest clause looked at for a loop.

The worst measured loop repeats eight words. Past a dozen the run is a person
making the same point twice, which is theirs to make.
"""

_WORD = re.compile(r"\S+")

_DANGLING = ("et", "ou", "mais", "donc", "car", "puis", "alors", "que", "qui")
"""Words a collapsed clause must not be left hanging on.

The loop is cut where the clause joins the next one, so what is left ends on
the join: *… de l'année, et.*
"""


def _blocks_are_equal(words: list[str], one: int, other: int, width: int) -> bool:
    return all(
        words[one + k].casefold().strip(",.;:!?…")
        == words[other + k].casefold().strip(",.;:!?…")
        for k in range(width)
    )


def without_loop(text: str) -> str:
    """The text with any clause repeated over and over brought back to twice.

    The shortest clause wins: a loop on three words is also a loop on six, and
    collapsing the short one leaves the least behind.
    """
    words = _WORD.findall(text)
    if len(words) < (REPEATS_ALLOWED + 1) * SHORTEST_LOOP:
        return text
    for width in range(SHORTEST_LOOP, min(LONGEST_LOOP, len(words) // 3) + 1):
        kept: list[str] = []
        position = 0
        found = False
        while position < len(words):
            repeats = 1
            while (position + (repeats + 1) * width <= len(words)
                   and _blocks_are_equal(words, position,
                                         position + repeats * width, width)):
                repeats += 1
            if repeats > REPEATS_ALLOWED:
                found = True
                kept += words[position:position + REPEATS_ALLOWED * width]
                position += repeats * width
                position += _tail_of_the_loop(words, position, position - width,
                                              width)
            else:
                kept += words[position:position + width]
                position += width
        if found:
            return _closed(" ".join(kept))
    return text


def _tail_of_the_loop(words: list[str], position: int, block: int,
                      width: int) -> int:
    """Words left over that only start the clause again, and end mid-loop.

    The model stops where the slice stops, so the last turn round is rarely a
    whole one: *… de l'année, et on est en vacuette de l'année.* Without this
    the fragment stays and the clause is said once more than allowed.
    """
    left = len(words) - position
    if left <= 0 or left >= width:
        return 0
    return left if _blocks_are_equal(words, position, block, left) else 0


def _closed(text: str) -> str:
    """A collapsed sentence ends where it was cut, not on a comma."""
    tidy = text.rstrip(" ,;:")
    while True:
        words = tidy.split()
        if not words or words[-1].casefold().strip(",.;:!?…") not in _DANGLING:
            break
        tidy = " ".join(words[:-1]).rstrip(" ,;:")
    if tidy and tidy[-1] not in ".!?…":
        tidy += "."
    return tidy
