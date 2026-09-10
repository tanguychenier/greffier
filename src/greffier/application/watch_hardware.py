"""Watches the audio hardware during the recording.

What matters is saying it **during** the meeting: a capture that stopped
growing, found out afterwards, is a meeting that no longer exists.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

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
    lister: Lister
    watch_rules: WatchRules
    reconstruire: Callable[[str], bool]
    notify_user: Callable[[str], None] = lambda _: None
    captured_size: Callable[[], int | None] | None = None
    captured_level: Callable[[], float | None] | None = None
    span: float = SPAN

    def __post_init__(self) -> None:
        self._precedent: Hardware | None = None
        self._capture = CaptureWatch()
        self._level = LevelWatch()

    def recorded(self) -> bool:
        """False as soon as the recording stops: the watch ends with it."""
        try:
            return self.recorder.read().phase is Phase.RECORDING
        except (OSError, ValueError):
            return False

    def turn(self) -> None:
        """One pass: whether capture advances and carries sound."""
        self._check_the_capture()
        self._check_the_level()
        current = self.lister.read()
        if not current.devices:
            return
        if self._precedent is None:
            self._precedent = current
            return

        decision = self.watch_rules.examine(self._precedent, current)
        self._precedent = current
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
