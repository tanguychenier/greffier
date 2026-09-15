"""How much meeting fits in what is left of the disk.

A recording is the one piece nothing rebuilds. The transcript comes from it,
the minutes come from the transcript, and a meeting whose recording stopped at
minute forty is forty minutes of meeting -- there is no second take of a
conversation between four people.

Nothing in the tool looked at the free space. The disk filling up during a
meeting is in the list of situations nobody had played, and it is the one with
the worst ending: ffmpeg stops writing, the window keeps showing a clock going
up, and the loss is only discovered afterwards.

The arithmetic is simple enough to be exact. Capture is 16 kHz, 16 bits, so
32 000 bytes a second per channel -- and the channels are counted, since a
video call records the microphone and the system output side by side.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

BYTES_PER_SECOND = 32_000
"""One channel of what the tool records: 16 kHz, 16 bits, no compression."""

ENOUGH_HOURS = 2.0
"""Above this, nothing is said.

Two hours, and not half an hour, because the warning has to come while it is
still actionable. The meetings measured run from 32 minutes to 1 h 42; being
told « 25 minutes left » as a two-hour meeting starts is being told after the
fact. Two hours clears the longest of them with room to spare.
"""

REFUSE_MINUTES = 5
"""Under this, starting is losing the recording, and keeping nothing."""


class Verdict(StrEnum):
    ENOUGH = "assez"
    TIGHT = "juste"
    TOO_LITTLE = "trop peu"


@dataclass(frozen=True, slots=True)
class Room:
    """What is left, said in meeting rather than in bytes."""

    free_bytes: int
    channels: int = 1

    def __post_init__(self) -> None:
        if self.channels < 1:
            raise ValueError("un enregistrement a au moins une voie")

    @property
    def seconds(self) -> float:
        return max(0.0, self.free_bytes / (BYTES_PER_SECOND * self.channels))

    @property
    def minutes(self) -> float:
        return self.seconds / 60

    @property
    def hours(self) -> float:
        return self.seconds / 3600

    @property
    def verdict(self) -> Verdict:
        if self.minutes < REFUSE_MINUTES:
            return Verdict.TOO_LITTLE
        if self.hours < ENOUGH_HOURS:
            return Verdict.TIGHT
        return Verdict.ENOUGH


def _readable(room: Room) -> str:
    """« 1 h 20 » or « 12 min », which is what somebody about to start needs."""
    if room.minutes >= 60:
        hours, minutes = divmod(int(room.minutes), 60)
        return f"{hours} h {minutes:02d}" if minutes else f"{hours} h"
    return f"{int(room.minutes)} min"


def said_in_french(room: Room) -> str:
    """The one line to show before starting, or nothing at all."""
    if room.verdict is Verdict.ENOUGH:
        return ""
    if room.verdict is Verdict.TOO_LITTLE:
        return (
            f"Il ne reste de la place que pour {_readable(room)} "
            "d'enregistrement. Un enregistrement interrompu ne se refait pas : "
            "libérez de la place avant de commencer."
        )
    return (
        f"Il reste de la place pour {_readable(room)} d'enregistrement. "
        "Au-delà, la capture s'arrête et ce qui n'a pas été écrit est perdu."
    )


def said_during_the_meeting(room: Room) -> str:
    """The one line to show while recording, or nothing at all.

    Said once and only when it is actionable: somebody in a meeting can delete
    something or stop early, and can do neither if the first they hear of it is
    the transcript missing its last half-hour.
    """
    if room.verdict is Verdict.ENOUGH:
        return ""
    return (
        f"Plus que {_readable(room)} d'enregistrement possible sur ce disque."
    )
