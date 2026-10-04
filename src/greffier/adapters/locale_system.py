"""What language this machine speaks, asked of the machine.

Asked rather than chosen: somebody who has already told their system what
language they read should not have to tell a tool as well. The setting exists
for the case where the two differ -- a French system and an English window,
which is a real preference and not a mistake.

Three systems, three places to ask: the shell's variables, macOS's `defaults`,
Windows's kernel32. Each answers something like `fr_FR.UTF-8`; Windows says
`fr-FR` and is brought to the same shape here. What to do with that is the
domain's business, not this file's.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform
import subprocess

SYSTEM = platform.system()

# LOCALE_NAME_MAX_LENGTH in the Windows headers: the longest locale name,
# terminator included, so the buffer handed to kernel32 is never too short.
LOCALE_NAME_MAX_LENGTH = 85


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


def _windows_user_locale_name() -> str:
    """The name Windows gives the user's locale, `fr-FR` style, asked of kernel32.

    `windll` is looked up with `getattr` because the type stubs declare it on
    Windows alone: a plain attribute would not type-check anywhere else, and
    its absence is also what says there is no Windows to ask.
    """
    loader = getattr(ctypes, "windll", None)
    if loader is None:
        return ""
    name = ctypes.create_unicode_buffer(LOCALE_NAME_MAX_LENGTH)
    written = loader.kernel32.GetUserDefaultLocaleName(name, LOCALE_NAME_MAX_LENGTH)
    return name.value if written else ""


def _from_windows() -> str:
    """The user's locale, in the shape the other systems give: `fr_FR`."""
    with contextlib.suppress(Exception):
        return _windows_user_locale_name().replace("-", "_")
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
    # On POSIX the environment is the locale: the C library itself learns it
    # from LC_ALL, LC_MESSAGES and LANG. `locale.getdefaultlocale`, which
    # stood here and which Python 3.15 removes, read LC_ALL, LC_CTYPE, LANG
    # and LANGUAGE: a subset of what `_from_the_environment` reads, plus
    # LC_CTYPE -- a character set, not a language. When the shell says
    # nothing, silence is the machine's answer, not a reading lost.
    return ""
