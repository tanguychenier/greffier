"""The two processes a meeting runs alongside itself.

The live thread and the hardware watch are started the same way whether the
meeting begins from the window or from the command line -- and the window used
to reach into the command line's private functions to do it, which is two
primary adapters leaning on each other. They belong here: starting a detached
process is adapter work, and neither of the two doors owns it.

Detached on purpose (`start_new_session`): a meeting must survive the window
being closed, and the two helpers must not die with the terminal that opened
them.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

SYSTEM = platform.system()


def _launch(command: list[str], log: Path) -> bool:
    """Starts it, keeping its output. False when it could not be started."""
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as trace:
            subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=trace, stderr=trace,
                start_new_session=True,
            )
    except OSError:
        return False
    return True


def _with_the_settings(command: list[str], config_file: Path | None) -> list[str]:
    return command + (["--config", str(config_file)] if config_file else [])


def start_the_watch(data: Path, config_file: Path | None = None) -> bool:
    """The hardware watch: macOS only, where a device can vanish mid-meeting.

    The verb is written out rather than passed in: a test reads the sources for
    what this tool launches of itself, and checks that every one of them is a
    command that exists. A verb behind a variable is a verb nobody checks.
    """
    if SYSTEM != "Darwin":
        return False
    return _launch(
        _with_the_settings(
            [sys.executable, "-m", "greffier", "veiller"], config_file),
        data / "veille.log",
    )


def start_the_live_thread(
    data: Path, active: bool, config_file: Path | None = None
) -> bool:
    """Live transcription, when the settings ask for it."""
    if not active:
        return False
    return _launch(
        _with_the_settings(
            [sys.executable, "-m", "greffier", "assister"], config_file),
        data / "direct.log",
    )
