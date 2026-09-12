"""A short sound telling the room what the assistant is doing.

A cue, not a voice: it says « I am going to look this up », and nothing else.
It is played at once and never waited for -- an answer must not be held up by a
sound card -- and it stays silent rather than fail when a machine has no way of
playing anything.

The file itself is brought down 18 dB from what the sound bank shipped. A cue
that sits at the level of the people talking is not a cue, it is an
interruption.
"""

from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Callable
from pathlib import Path

SOUNDS = Path(__file__).resolve().parent.parent / "sounds"

WEB_SEARCH = SOUNDS / "web-search.wav"

#: Played when a spoken sentence has been taken in, outside a meeting. In the
#: room the assistant stays silent, and a cue on every sentence would be
#: unbearable; preparing alone, the opposite is true -- somebody who has just
#: spoken to a machine and hears nothing at all wonders whether the microphone
#: is on, and says it again.
HEARD = SOUNDS / "heard.wav"


def cue(file: Path = WEB_SEARCH) -> Callable[[], None]:
    """Something to call when the moment comes; silent when it cannot play.

    Decided once, at wiring time, rather than at every call: looking for a
    player costs a few `which` and the answer never changes during a meeting.
    """
    from greffier.adapters.voice_neural import player

    command = player()
    if command is None or not file.exists():
        return lambda: None

    def sonner() -> None:
        # A sound that cannot be played is not a reason to lose an answer.
        with contextlib.suppress(OSError):
            subprocess.Popen(
                [*command, str(file)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    return sonner
