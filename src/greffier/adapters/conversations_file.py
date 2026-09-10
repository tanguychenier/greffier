"""The conversation, kept on disk, meeting by meeting."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TOURS_RELUS = 60

@dataclass(frozen=True, slots=True)
class Exchange:
    """One turn of the conversation, as it was kept."""

    qui: str
    text: str
    quand: datetime | None = None

def file_for(folder: Path, identifier: str) -> Path:
    return folder / f"{identifier}.jsonl"

def add(file: Path, qui: str, text: str) -> None:
    """Appends a turn. Never fails loudly."""
    if not text.strip():
        return
    with contextlib.suppress(OSError):
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as flux:
            flux.write(json.dumps(
                {"qui": qui, "texte": text,
                 "quand": datetime.now(UTC).isoformat()},
                ensure_ascii=False,
            ) + "\n")

def read(file: Path, derniers: int = TOURS_RELUS) -> list[Exchange]:
    """The last turns of the conversation, oldest first."""
    if not file.exists():
        return []
    turns: list[Exchange] = []
    with contextlib.suppress(OSError):
        for brute in file.read_text(encoding="utf-8").splitlines():
            if not brute.strip():
                continue
            try:
                line = json.loads(brute)
            except json.JSONDecodeError:
                continue
            if not isinstance(line, dict) or not str(line.get("texte", "")).strip():
                continue
            quand = None
            with contextlib.suppress(ValueError, TypeError):
                quand = datetime.fromisoformat(str(line.get("quand", "")))
            turns.append(Exchange(
                qui=str(line.get("qui", "note")),
                text=str(line["texte"]),
                quand=quand,
            ))
    return turns[-derniers:] if derniers > 0 else turns
