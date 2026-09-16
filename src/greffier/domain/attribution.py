"""Who a transcribed sentence belongs to, when the two cuts disagree.

The transcriber cuts at the sentence, the segmenter at the speaker turn, and
the two boundaries never coincide.
"""

from __future__ import annotations

from greffier.domain.models import Span, SpeakerTurn

MINIMUM_SHARE = 0.80

def time_per_voice(span: Span, turns: list[SpeakerTurn]) -> dict[str, float]:
    """How many seconds each voice holds during this span."""
    totals: dict[str, float] = {}
    for turn in turns:
        shared_one = span.overlap(turn.span)
        if shared_one > 0:
            totals[turn.voice] = totals.get(turn.voice, 0.0) + shared_one
    return totals

def voice_of(
    span: Span,
    turns: list[SpeakerTurn],
    minimum_share: float = MINIMUM_SHARE,
) -> str | None:
    """The voice this sentence belongs to, or None when it straddles two.

    Straddling means nobody rather than the most talkative: a sentence given to the
    wrong person is worse in the minutes than a sentence given to no one.
    """
    totals = time_per_voice(span, turns)
    if not totals:
        return None
    total = sum(totals.values())
    leader = max(totals, key=lambda voice: totals[voice])
    if total <= 0 or totals[leader] / total < minimum_share:
        return None
    return leader
