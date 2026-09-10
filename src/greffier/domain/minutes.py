"""What is read in minutes, without knowing how they will be delivered."""

from __future__ import annotations

import re

_GRAS = re.compile(r"\*\*(.+?)\*\*")

def title(minutes: str, defaut: str) -> str:
    """Email subject: the title of the minutes, not the name of the file."""
    for line in minutes.splitlines():
        nue = line.strip()
        if nue.startswith("# "):
            title = _GRAS.sub(r"\1", nue[2:].strip())
            return title or defaut
        if nue:
            break
    return defaut
