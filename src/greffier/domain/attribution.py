"""Who a transcribed sentence belongs to, when the two cuts disagree.

The transcriber cuts at the sentence, the segmenter at the speaker turn, and
the two boundaries never coincide.
"""

from __future__ import annotations

from greffier.domain.models import Span, SpeakerTurn

PART_MINIMALE = 0.80

def time_per_voice(span: Span, turns: list[SpeakerTurn]) -> dict[str, float]:
    """How many seconds each voice holds during this span."""
    cumuls: dict[str, float] = {}
    for turn in turns:
        commun = span.overlap(turn.span)
        if commun > 0:
            cumuls[turn.voice] = cumuls.get(turn.voice, 0.0) + commun
    return cumuls

def voice_of(
    span: Span,
    turns: list[SpeakerTurn],
    part_minimale: float = PART_MINIMALE,
) -> str | None:
    """The voice this sentence belongs to, or None when it straddles two.

    Straddling means nobody rather than the most talkative: a sentence given to the
    wrong person is worse in the minutes than a sentence given to no one.
    """
    cumuls = time_per_voice(span, turns)
    if not cumuls:
        return None
    total = sum(cumuls.values())
    meneur = max(cumuls, key=lambda voice: cumuls[voice])
    if total <= 0 or cumuls[meneur] / total < part_minimale:
        return None
    return meneur
