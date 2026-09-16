"""Who speaks, according to the channel the sound arrives on.

The only knowledge here that comes from no model: it is wiring. A voice on the
mic belongs to whoever is recording, and that is never wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from greffier.domain.models import Span

LOCAL_VOICE = "moi"

MARGIN_DB = 6.0

FLOOR_DB = -45.0

STITCH_S = 0.7

MINIMUM_LENGTH_S = 0.8

@dataclass(frozen=True)
class ChannelSettings:
    """What can be tuned without touching the code."""

    margin_db: float = MARGIN_DB
    floor_db: float = FLOOR_DB
    stitch_s: float = STITCH_S
    minimum_length_s: float = MINIMUM_LENGTH_S

class WhoSpeaks(StrEnum):
    """What an interface may show during the meeting, without a model."""

    NOBODY = "personne"
    YOU = "toi"
    THE_OTHERS = "les autres"
    BOTH = "les deux"

VIDEO_SHARE = 0.05

def over_video(
    mic_db: list[float],
    system_db: list[float],
    settings: ChannelSettings | None = None,
) -> bool:
    """Whether the meeting was held remotely, from the two channels."""
    r = settings or ChannelSettings()
    useful_ones = min(len(mic_db), len(system_db))
    if useful_ones == 0:
        return False
    domine = sum(
        1
        for i in range(useful_ones)
        if system_db[i] > mic_db[i] + r.margin_db and system_db[i] > r.floor_db
    )
    return domine / useful_ones >= VIDEO_SHARE

def who_speaks(
    mic_db: float,
    system_db: float,
    settings: ChannelSettings | None = None,
) -> WhoSpeaks:
    """Who holds the floor at this instant, from the two channels."""
    r = settings or ChannelSettings()
    mic = mic_db > r.floor_db
    system = system_db > r.floor_db
    if mic and system:
        return WhoSpeaks.BOTH if mic_db > system_db + r.margin_db else WhoSpeaks.THE_OTHERS
    if mic:
        return WhoSpeaks.YOU
    if system:
        return WhoSpeaks.THE_OTHERS
    return WhoSpeaks.NOBODY

def local_turns(
    mic_db: list[float],
    system_db: list[float],
    step_s: float,
    settings: ChannelSettings | None = None,
) -> list[Span]:
    """The moments when the person recording speaks themselves."""
    r = settings or ChannelSettings()
    if step_s <= 0:
        raise ValueError("le pas des trames doit être positif")

    useful_ones = min(len(mic_db), len(system_db))
    local_ones = [
        mic_db[i] > system_db[i] + r.margin_db and mic_db[i] > r.floor_db
        for i in range(useful_ones)
    ]
    return _regroup(local_ones, step_s, r)

def _regroup(local_ones: list[bool], step_s: float, r: ChannelSettings) -> list[Span]:
    """Assembles frames into spans, closing the short silences."""
    plages: list[tuple[int, int]] = []
    start: int | None = None
    last = 0
    for i, active in enumerate(local_ones):
        if active:
            if start is None:
                start = i
            last = i
        elif start is not None and (i - last) * step_s > r.stitch_s:
            plages.append((start, last + 1))
            start = None
    if start is not None:
        plages.append((start, last + 1))

    return [
        Span(a * step_s, b * step_s)
        for a, b in plages
        if (b - a) * step_s >= r.minimum_length_s
    ]

def subtract(span: Span, others: list[Span]) -> list[Span]:
    """What is left of a span once the others are taken out of it."""
    remainders = [span]
    for other in others:
        next_ones: list[Span] = []
        for remaining in remainders:
            if other.end <= remaining.start or other.start >= remaining.end:
                next_ones.append(remaining)
                continue
            if other.start > remaining.start:
                next_ones.append(Span(remaining.start, other.start))
            if other.end < remaining.end:
                next_ones.append(Span(other.end, remaining.end))
        remainders = next_ones
    return remainders

def remove(turns: list[Span], local_spans: list[Span]) -> list[Span]:
    """Takes out of the remote turns whatever a local turn covers."""
    if not local_spans:
        return turns
    remaining: list[Span] = []
    for turn in turns:
        couvert = sum(
            max(0.0, min(turn.end, local.end) - max(turn.start, local.start))
            for local in local_spans
        )
        if turn.duration <= 0 or couvert / turn.duration < 0.5:
            remaining.append(turn)
    return remaining

#: How long the room has to be quiet before somebody is taken to have finished.
QUIET_S = 0.5

@dataclass
class SpeechEnd:
    """Says, from level snapshots, the moment somebody has just stopped talking.

    The pass that listens for the assistant's name used to run on the clock,
    every three seconds: a question that ended right after a pass waited for
    the next one, and a pass that landed in the middle of one read half a
    question. The moment somebody stops is the moment to listen.

    Snapshots come when whoever watches has time to look, and a pass takes
    seconds: an end noticed late is still an end, and still the earliest
    moment there is to listen.
    """

    quiet_s: float = QUIET_S
    last_speech_at: float | None = None
    announced_at: float | None = None
    noted_at: float | None = None

    def note(self, at: float, speaking: bool) -> bool:
        """Records one snapshot; True once, when a speech has just ended."""
        self.noted_at = at
        if speaking:
            self.last_speech_at = at
            return False
        if self.last_speech_at is None or self.announced_at == self.last_speech_at:
            return False
        if at - self.last_speech_at < self.quiet_s:
            return False
        self.announced_at = self.last_speech_at
        return True

    def spoken_since(self, moment: float) -> bool:
        """Whether anyone spoke after `moment`, as far as the snapshots know.

        True when nothing was ever noted: with no level to read, the caller
        cannot tell, and must act as if somebody had.
        """
        if self.noted_at is None:
            return True
        return self.last_speech_at is not None and self.last_speech_at > moment
