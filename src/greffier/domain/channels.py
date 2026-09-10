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
    reglages: ChannelSettings | None = None,
) -> bool:
    """Whether the meeting was held remotely, from the two channels."""
    r = reglages or ChannelSettings()
    utiles = min(len(mic_db), len(system_db))
    if utiles == 0:
        return False
    domine = sum(
        1
        for i in range(utiles)
        if system_db[i] > mic_db[i] + r.margin_db and system_db[i] > r.floor_db
    )
    return domine / utiles >= VIDEO_SHARE

def who_speaks(
    mic_db: float,
    system_db: float,
    reglages: ChannelSettings | None = None,
) -> WhoSpeaks:
    """Who holds the floor at this instant, from the two channels."""
    r = reglages or ChannelSettings()
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
    reglages: ChannelSettings | None = None,
) -> list[Span]:
    """The moments when the person recording speaks themselves."""
    r = reglages or ChannelSettings()
    if step_s <= 0:
        raise ValueError("le pas des trames doit être positif")

    utiles = min(len(mic_db), len(system_db))
    local_ones = [
        mic_db[i] > system_db[i] + r.margin_db and mic_db[i] > r.floor_db
        for i in range(utiles)
    ]
    return _regroup(local_ones, step_s, r)

def _regroup(local_ones: list[bool], step_s: float, r: ChannelSettings) -> list[Span]:
    """Assembles frames into spans, closing the short silences."""
    plages: list[tuple[int, int]] = []
    start: int | None = None
    dernier = 0
    for i, active in enumerate(local_ones):
        if active:
            if start is None:
                start = i
            dernier = i
        elif start is not None and (i - dernier) * step_s > r.stitch_s:
            plages.append((start, dernier + 1))
            start = None
    if start is not None:
        plages.append((start, dernier + 1))

    return [
        Span(a * step_s, b * step_s)
        for a, b in plages
        if (b - a) * step_s >= r.minimum_length_s
    ]

def subtract(span: Span, autres: list[Span]) -> list[Span]:
    """What is left of a span once the others are taken out of it."""
    restes = [span]
    for autre in autres:
        suivants: list[Span] = []
        for reste in restes:
            if autre.end <= reste.start or autre.start >= reste.end:
                suivants.append(reste)
                continue
            if autre.start > reste.start:
                suivants.append(Span(reste.start, autre.start))
            if autre.end < reste.end:
                suivants.append(Span(autre.end, reste.end))
        restes = suivants
    return restes

def remove(turns: list[Span], locaux: list[Span]) -> list[Span]:
    """Takes out of the remote turns whatever a local turn covers."""
    if not locaux:
        return turns
    restants: list[Span] = []
    for turn in turns:
        couvert = sum(
            max(0.0, min(turn.end, local.end) - max(turn.start, local.start))
            for local in locaux
        )
        if turn.duration <= 0 or couvert / turn.duration < 0.5:
            restants.append(turn)
    return restants
