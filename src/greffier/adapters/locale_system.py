"""What language this machine speaks, asked of the machine.

Asked rather than chosen: somebody who has already told their system what
language they read should not have to tell a tool as well. The setting exists
for the case where the two differ -- a French system and an English window,
which is a real preference and not a mistake.

Three systems, three places to ask. Each answers something like `fr_FR.UTF-8`;
what to do with that is the domain's business, not this file's.
"""

from __future__ import annotations

import locale
import os
import platform
import subprocess

SYSTEM = platform.system()


def _from_the_environment() -> str:
    """POSIX, and the first thing to try everywhere: the shell knows."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(variable, "").strip()
        if value and value not in ("C", "POSIX"):
            return value.split(":")[0]
    return ""


def _from_macos() -> str:
    """The user's chosen languages, which need not match the shell's."""
    try:
        read = subprocess.run(
            ["defaults", "read", "-g", "AppleLocale"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return read.stdout.strip() if read.returncode == 0 else ""


def _from_windows() -> str:
    with __import__("contextlib").suppress(Exception):
        code, _ = locale.getdefaultlocale()
        return code or ""
    return ""


def read() -> str:
    """The machine's language, as it gives it, or an empty string.

    Order matters: an explicit environment beats a system preference, because
    somebody who exports `LANG` for a session means it for that session.
    """
    said = _from_the_environment()
    if said:
        return said
    if SYSTEM == "Darwin":
        return _from_macos()
    if SYSTEM == "Windows":
        return _from_windows()
    with __import__("contextlib").suppress(Exception):
        code, _ = locale.getdefaultlocale()
        return code or ""
    return ""
