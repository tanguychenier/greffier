"""Preparations, one file each, next to the meetings they will open.

A file rather than a line in a log: a preparation is written to again and again
-- a question, an answer, a document, a name expected -- where a meeting's trace
is written once and never touched. Rewritten whole each time, which costs
nothing at this size and leaves a file a person can open and correct.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.preparation import Exchange, Preparation


def file_for(folder: Path, identifier: str) -> Path:
    return folder / f"{identifier}.json"


def open_one(folder: Path, subject: str = "") -> Preparation:
    """Starts a preparation, named after the moment it was opened."""
    now = datetime.now(UTC).astimezone()
    preparation = Preparation(
        identifier=now.strftime("%Y-%m-%d_%Hh%M_preparation"),
        subject=subject.strip(),
        opened_on=now.date().isoformat(),
    )
    write(folder, preparation)
    return preparation


def write(folder: Path, preparation: Preparation) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    file = file_for(folder, preparation.identifier)
    file.write_text(
        json.dumps(asdict(preparation), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return file


def read(folder: Path, identifier: str) -> Preparation | None:
    file = file_for(folder, identifier)
    if not file.exists():
        return None
    try:
        lu = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(lu, dict) or not lu.get("identifier"):
        return None
    return Preparation(
        identifier=str(lu["identifier"]),
        subject=str(lu.get("subject", "")),
        opened_on=str(lu.get("opened_on", "")),
        exchanges=tuple(
            Exchange(asked=str(e.get("asked", "")), answered=str(e.get("answered", "")))
            for e in lu.get("exchanges") or []
            if isinstance(e, dict)
        ),
        documents=tuple(lu.get("documents") or ()),
        to_raise=tuple(lu.get("to_raise") or ()),
        expected=tuple(lu.get("expected") or ()),
        taken_by=str(lu.get("taken_by", "")),
    )


def lister(folder: Path) -> list[Preparation]:
    """The preparations, most recent first."""
    if not folder.is_dir():
        return []
    lues = [read(folder, file.stem) for file in sorted(folder.glob("*.json"))]
    return [p for p in reversed(lues) if p is not None]


def waiting(folder: Path) -> Preparation | None:
    """The one a meeting starting now would open on, if there is one.

    The most recent that no meeting has taken. Consumed once: two meetings
    opening on the same material would each believe it was theirs.
    """
    return next((p for p in lister(folder) if p.available), None)
