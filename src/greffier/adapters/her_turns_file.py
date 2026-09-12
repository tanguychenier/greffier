"""When the assistant spoke, kept for the processing that comes after.

It knows its own speaking turns while a meeting runs, and forgets them with the
process that held them. The chain then runs an hour later, in another process,
and finds a voice nobody owns.

One line per remark, appended next to the meeting's live thread: the same shape
as everything else written during a meeting, readable by a person, and costing
nothing to append while somebody is talking.
"""

from __future__ import annotations

import json
from pathlib import Path


def file_for(folder: Path, identifier: str) -> Path:
    return folder / f"{identifier}-assistante.jsonl"

def keep(file: Path, start: float, end: float) -> None:
    """Files one of her speaking turns. Never raises: she is talking."""
    if end <= start:
        return
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as sortie:
            sortie.write(json.dumps({"de": round(start, 2), "a": round(end, 2)}) + "\n")
    except OSError:
        pass

def read(file: Path) -> list[tuple[float, float]]:
    """Her speaking turns, the unreadable lines passed over."""
    if not file.exists():
        return []
    intervalles: list[tuple[float, float]] = []
    for ligne in file.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            lu = json.loads(ligne)
            intervalles.append((float(lu["de"]), float(lu["a"])))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return intervalles
