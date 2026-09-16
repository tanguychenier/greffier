"""What earlier meetings left, kept in one file next to the meetings themselves.

One line per meeting, appended: a file that is read whole, written by one
process at a time, and that a person can open and correct. A database would
carry no more here, and would not survive being copied from one machine to
another the way this does.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from greffier.domain.memory import Trace

#: Read back at most this many meetings. What the header can carry is bounded
#: anyway; reading a hundred lines to keep four would only cost disk.
DERNIERES = 12


def file_in(folder: Path) -> Path:
    return folder / "memoire.jsonl"


def remember(file: Path, trace: Trace) -> None:
    """Files what a meeting left. Never raises: minutes are worth more."""
    if trace.empty:
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(trace), ensure_ascii=False)
    with file.open("a", encoding="utf-8") as output_:
        output_.write(line + "\n")


def recall(file: Path, limit: int = DERNIERES) -> list[Trace]:
    """The most recent meetings first, the unreadable lines passed over.

    A line that cannot be read is skipped rather than fatal: this file is meant
    to be openable by a person, and a person editing a file makes mistakes.
    """
    if not file.exists():
        return []
    traces: list[Trace] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            read_ = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(read_, dict) or "identifier" not in read_:
            continue
        traces.append(Trace(
            identifier=str(read_.get("identifier", "")),
            title=str(read_.get("title", "")),
            held_on=str(read_.get("held_on", "")),
            people=tuple(read_.get("people") or ()),
            decisions=tuple(read_.get("decisions") or ()),
            open_points=tuple(read_.get("open_points") or ()),
            documents=tuple(read_.get("documents") or ()),
        ))
    derniers = traces[-limit:]
    derniers.reverse()
    return derniers
