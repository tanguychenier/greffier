"""Who speaks, according to the channel the sound arrives on.

The only knowledge here that comes from no model: it is wiring. A voice on the
mic belongs to whoever is recording, and that is never wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from greffier.domain.models import Span

VOIX_LOCALE = "moi"

MARGE_DB = 6.0

PLANCHER_DB = -45.0

RECOLLAGE_S = 0.7

DUREE_MINIMALE_S = 0.8

@dataclass(frozen=True)
class ChannelSettings:
    """What can be tuned without touching the code."""

    marge_db: float = MARGE_DB
    plancher_db: float = PLANCHER_DB
    recollage_s: float = RECOLLAGE_S
    duree_minimale_s: float = DUREE_MINIMALE_S

class WhoSpeaks(StrEnum):
    """What an interface may show during the meeting, without a model."""

    PERSONNE = "personne"
    TOI = "toi"
    LES_AUTRES = "les autres"
    LES_DEUX = "les deux"

PART_VISIO = 0.05

def over_video(
    micro_db: list[float],
    systeme_db: list[float],
    reglages: ChannelSettings | None = None,
) -> bool:
    """Whether the meeting was held remotely, from the two channels."""
    r = reglages or ChannelSettings()
    utiles = min(len(micro_db), len(systeme_db))
    if utiles == 0:
        return False
    domine = sum(
        1
        for i in range(utiles)
        if systeme_db[i] > micro_db[i] + r.marge_db and systeme_db[i] > r.plancher_db
    )
    return domine / utiles >= PART_VISIO

def who_speaks(
    micro_db: float,
    systeme_db: float,
    reglages: ChannelSettings | None = None,
) -> WhoSpeaks:
    """Who holds the floor at this instant, from the two channels."""
    r = reglages or ChannelSettings()
    mic = micro_db > r.plancher_db
    system = systeme_db > r.plancher_db
    if mic and system:
        return WhoSpeaks.LES_DEUX if micro_db > systeme_db + r.marge_db else WhoSpeaks.LES_AUTRES
    if mic:
        return WhoSpeaks.TOI
    if system:
        return WhoSpeaks.LES_AUTRES
    return WhoSpeaks.PERSONNE

def local_turns(
    micro_db: list[float],
    systeme_db: list[float],
    pas_s: float,
    reglages: ChannelSettings | None = None,
) -> list[Span]:
    """The moments when the person recording speaks themselves."""
    r = reglages or ChannelSettings()
    if pas_s <= 0:
        raise ValueError("le pas des trames doit être positif")

    utiles = min(len(micro_db), len(systeme_db))
    locales = [
        micro_db[i] > systeme_db[i] + r.marge_db and micro_db[i] > r.plancher_db
        for i in range(utiles)
    ]
    return _regrouper(locales, pas_s, r)

def _regrouper(locales: list[bool], pas_s: float, r: ChannelSettings) -> list[Span]:
    """Assembles frames into spans, closing the short silences."""
    plages: list[tuple[int, int]] = []
    start: int | None = None
    dernier = 0
    for i, active in enumerate(locales):
        if active:
            if start is None:
                start = i
            dernier = i
        elif start is not None and (i - dernier) * pas_s > r.recollage_s:
            plages.append((start, dernier + 1))
            start = None
    if start is not None:
        plages.append((start, dernier + 1))

    return [
        Span(a * pas_s, b * pas_s)
        for a, b in plages
        if (b - a) * pas_s >= r.duree_minimale_s
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
