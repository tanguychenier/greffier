"""What is read in minutes, without knowing how they will be delivered."""

from __future__ import annotations

import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")

def title(minutes: str, defect: str) -> str:
    """Email subject: the title of the minutes, not the name of the file."""
    for line in minutes.splitlines():
        bare = line.strip()
        if bare.startswith("# "):
            title = _BOLD.sub(r"\1", bare[2:].strip())
            return title or defect
        if bare:
            break
    return defect
