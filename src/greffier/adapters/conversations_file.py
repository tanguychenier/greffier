"""The conversation, kept on disk, meeting by meeting."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TURNS_REREAD = 60

@dataclass(frozen=True, slots=True)
class Exchange:
    """One turn of the conversation, as it was kept."""

    who: str
    text: str
    when: datetime | None = None

def file_for(folder: Path, identifier: str) -> Path:
    return folder / f"{identifier}.jsonl"

def add(file: Path, who: str, text: str) -> None:
    """Appends a turn. Never fails loudly."""
    if not text.strip():
        return
    with contextlib.suppress(OSError):
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(
                {"qui": who, "texte": text,
                 "quand": datetime.now(UTC).isoformat()},
                ensure_ascii=False,
            ) + "\n")

def read(file: Path, derniers: int = TURNS_REREAD) -> list[Exchange]:
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
            when = None
            with contextlib.suppress(ValueError, TypeError):
                when = datetime.fromisoformat(str(line.get("quand", "")))
            turns.append(Exchange(
                who=str(line.get("qui", "note")),
                text=str(line["texte"]),
                when=when,
            ))
    return turns[-derniers:] if derniers > 0 else turns
