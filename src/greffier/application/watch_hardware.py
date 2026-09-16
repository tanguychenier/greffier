"""Watches the audio hardware during the recording.

What matters is saying it **during** the meeting: a capture that stopped
growing, found out afterwards, is a meeting that no longer exists.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from greffier.domain import space
from greffier.domain.capture import CaptureWatch
from greffier.domain.devices import Action, Hardware, WatchRules
from greffier.domain.level import LevelWatch
from greffier.domain.models import Phase

SPAN = 4.0

class Lister(Protocol):
    """What is expected of reading the hardware."""

    def read(self) -> Hardware: ...  # pragma: no cover

class Recorder(Protocol):
    """What is expected of the recording state machine."""

    def read(self) -> Any: ...  # pragma: no cover

    def reprendre(self, because: str) -> Any: ...  # pragma: no cover

    def report(self, warning: str) -> Any: ...  # pragma: no cover

@dataclass
class HardwareWatch:
    """One watch pass, isolated from the clock and the hardware."""

    recorder: Recorder
    list_: Lister
    watch_rules: WatchRules
    reconstruire: Callable[[str], bool]
    notify_user: Callable[[str], None] = lambda _: None
    captured_size: Callable[[], int | None] | None = None
    captured_level: Callable[[], float | None] | None = None
    room_left: Callable[[], int | None] | None = None
    channels: int = 1
    span: float = SPAN

    def __post_init__(self) -> None:
        self._previous: Hardware | None = None
        self._capture = CaptureWatch()
        self._level = LevelWatch()
        self._said_the_disk_is_filling = False

    def recorded(self) -> bool:
        """False as soon as the recording stops: the watch ends with it."""
        try:
            return self.recorder.read().phase is Phase.RECORDING
        except (OSError, ValueError):
            return False

    def turn(self) -> None:
        """One pass: whether capture advances, carries sound, and has room."""
        self._check_the_capture()
        self._check_the_level()
        self._check_the_room_left()
        current = self.list_.read()
        if not current.devices:
            return
        if self._previous is None:
            self._previous = current
            return

        decision = self.watch_rules.examine(self._previous, current)
        self._previous = current
        if decision.action is Action.NOTHING:
            return

        if decision.action is Action.ALERTER:
            self.recorder.report(decision.because)
            self.notify_user(decision.because)
            return

        if not self.reconstruire(decision.mic):
            self.recorder.report(
                f"{decision.because} La reconstruction du périphérique a échoué : "
                "la capture continue sur l'ancien."
            )
            self.notify_user("Changement de matériel non pris en compte.")
            return
        self.recorder.reprendre(decision.because)
        self.notify_user(decision.because)

    def _check_the_capture(self) -> None:
        """Says at once when nothing is being written any more."""
        if self.captured_size is None:
            return
        bytes_read = self.captured_size()
        if bytes_read is None:
            return
        because = self._capture.observe(bytes_read)
        if not because:
            return
        self.recorder.report(because)
        self.notify_user("L'enregistrement n'avance plus.")

    def _check_the_room_left(self) -> None:
        """Says, once, that the disk will not hold the rest of the meeting.

        Once and not every pass: a watch that repeats itself every ten seconds
        is a watch people learn to ignore. And said while it can still be acted
        on -- somebody in a meeting can free something up or stop early, and
        can do neither if the first they hear of it is a transcript missing its
        last half-hour.
        """
        if self.room_left is None or self._said_the_disk_is_filling:
            return
        libre = self.room_left()
        if libre is None:
            return
        because = space.said_during_the_meeting(space.Room(libre, self.channels))
        if not because:
            return
        self._said_the_disk_is_filling = True
        self.recorder.report(because)
        self.notify_user(because)

    def _check_the_level(self) -> None:
        """Says, once, that the captured sound is too weak to transcribe."""
        if self.captured_level is None:
            return
        db = self.captured_level()
        if db is None:
            return
        because = self._level.observe(db)
        if not because:
            return
        self.recorder.report(because)
        self.notify_user("Le son capté est trop faible.")

    def loop(self, dormir: Callable[[float], None] = time.sleep) -> int:
        """Watches until the recording stops."""
        turns = 0
        while self.recorded():
            self.turn()
            turns += 1
            dormir(self.span)
        return turns
