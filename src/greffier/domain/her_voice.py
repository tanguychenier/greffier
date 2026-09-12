"""Telling the assistant's own voice from the room's.

What it says leaves the speakers and comes straight back in through the capture
of everybody else's sound. The separation then hears a voice nobody in the room
owns, counts it as a participant, and asks for its name -- reported in use:
« ça détectait mal les voix et en rajoutait à chaque fois ». One of them was
Lucie answering a question.

It knows when it spoke: it keeps the intervals as it speaks them. All that is
needed is to compare. Pure, and deliberately generous about the ends -- speech
synthesis does not stop on the millisecond it announced.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

PART_MINIMUM = 0.5

MARGE_S = 0.4

def is_hers(
    start: float, end: float,
    intervals: Iterable[tuple[float, float]],
    part: float = PART_MINIMUM,
) -> bool:
    """Whether this passage is mostly the assistant speaking."""
    if end <= start:
        return False
    return any(
        min(end, sa_fin + MARGE_S) - max(start, son_debut - MARGE_S)
        > part * (end - start)
        for son_debut, sa_fin in intervals
    )

def voices_of(
    turns: Sequence[object],
    intervals: Iterable[tuple[float, float]],
    part: float = PART_MINIMUM,
) -> set[str]:
    """The voices that are the assistant rather than somebody in the room.

    Judged on the whole of a voice and not on one passage: the separation hands
    out a voice per timbre, so a voice that is hers is hers throughout, and one
    stray overlap must not take a participant away from the room.
    """
    gardes: dict[str, list[float]] = {}
    for turn in turns:
        span = turn.span  # type: ignore[attr-defined]
        duree = span.end - span.start
        if duree <= 0:
            continue
        sien = is_hers(span.start, span.end, intervals, part)
        compte = gardes.setdefault(turn.voice, [0.0, 0.0])  # type: ignore[attr-defined]
        compte[0] += duree if sien else 0.0
        compte[1] += duree
    return {
        voice for voice, (sienne, totale) in gardes.items()
        if totale > 0 and sienne > part * totale
    }
