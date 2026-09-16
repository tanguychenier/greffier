"""Erasing somebody from everything the tool kept of them.

« greffier connus --oublier » takes the voiceprint out of the bank, which is the
biometric half and the half everybody thinks of. The other half stayed where it
was: the first name sits in every master file, in the minutes, in the readable
transcript, in the live thread, in the questions, in the conversations with the
assistant, in the memory carried from one meeting to the next, in the index and
in the meetings prepared but not yet held. Somebody who asked to be forgotten
was still named in nine places out of ten.

Two decisions shape what follows.

**A meeting is not erased with the person.** What was decided around that table
belongs to everyone who was there, and one participant cannot withdraw the
record of it. So the turn stays, the sentence stays, and the name becomes
« Indéterminé » -- which is what the window already shows for a voice nobody has
named, and exactly what that voice is again once its name is gone.

**The inventory comes before the erasure**, the way it does for a meeting. This
cannot be undone, it touches files somebody may have sent elsewhere, and a
first name is a common word: « Camille » in a sentence about somebody else is
caught too. Saying where the name stands, and how many times, is the only
honest way to ask.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from greffier.domain.erasure import UNNAMED, count, redact

#: What holds a name and is not plain text: read, rewritten field by field.
STRUCTURED = ".json"


@dataclass(frozen=True, slots=True)
class Everywhere:
    """Where a person can have been written down.

    Optional because a machine that has never held a meeting has none of these
    folders, and because the bank and the index are reached through what the
    caller passes rather than through a path this module would open itself.
    """

    meetings: Path
    minutes_folder: Path
    transcripts: Path
    live: Path
    propositions: Path
    questions: Path | None = None
    conversations: Path | None = None
    preparations: Path | None = None
    memory: Path | None = None
    troubles: Path | None = None


@dataclass(frozen=True, slots=True)
class Trace:
    """One place the name was found, and how many times."""

    path: Path
    what: str
    occurrences: int
    biometric: bool = False


@dataclass(slots=True)
class Erased:
    """What an erasure did, said in the terms of the inventory."""

    traces: list[Trace] = field(default_factory=list)
    voiceprints: int = 0
    index_entries: int = 0

    @property
    def occurrences(self) -> int:
        return sum(trace.occurrences for trace in self.traces)

    @property
    def files(self) -> int:
        return len(self.traces)


def _files_of(where_: Everywhere) -> Iterator[tuple[Path, str]]:
    """Every file that can hold a name, with what it is in French."""
    folders = [
        (where_.meetings, "*.json", "réunion transcrite"),
        (where_.minutes_folder, "*.md", "compte rendu"),
        (where_.transcripts, "*.txt", "transcription lisible"),
        (where_.live, "*.jsonl", "fil du direct"),
        (where_.propositions, "*.jsonl", "propositions de noms"),
        (where_.questions, "*.jsonl", "questions posées"),
        (where_.conversations, "*.jsonl", "conversation avec l'assistant"),
        (where_.preparations, "*.json", "réunion préparée"),
    ]
    for folder, motif, what in folders:
        if folder is None or not folder.is_dir():
            continue
        for path in sorted(folder.glob(motif)):
            yield path, what
    for file, what in ((where_.memory, "mémoire des réunions"),
                       (where_.troubles, "journal des incidents")):
        if file is not None and file.is_file():
            yield file, what


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def inventory(where_: Everywhere, name: str, voiceprints: int = 0) -> list[Trace]:
    """Where this name stands, heaviest first, without touching anything."""
    traces = [
        Trace(path, what, how_many)
        for path, what in _files_of(where_)
        if (content := _read(path)) is not None
        and (how_many := count(content, name))
    ]
    if voiceprints:
        traces.append(Trace(
            Path("banque-de-voix"), "empreintes vocales", voiceprints,
            biometric=True,
        ))
    return sorted(traces, key=lambda trace: (-trace.occurrences, str(trace.path)))


def _rewrite_json(content: str, name: str, replacement: str) -> tuple[str, int]:
    """A master file rewritten key by key, so the file stays a file.

    Blunt redaction would work on the text, and would also rewrite an
    identifier, a path or a date that happened to hold the name -- a meeting
    recorded in `2026-09-10_sophie.wav` would come back pointing at a recording
    that does not exist. Only the values that hold speech or a name are
    touched, and the shape of the document is kept exactly.
    """
    try:
        document = json.loads(content)
    except json.JSONDecodeError:
        return redact(content, name, replacement)

    how_many = 0

    def walk(node: object, under: str) -> object:
        nonlocal how_many
        if isinstance(node, dict):
            fresh: dict[str, object] = {}
            for key, value in node.items():
                key_name, replaced = redact(key, name, replacement)
                how_many += replaced
                fresh[key_name] = walk(value, key)
            return fresh
        if isinstance(node, list):
            return [walk(value, under) for value in node]
        if isinstance(node, str) and under not in ("audio", "identifiant"):
            text, replaced = redact(node, name, replacement)
            how_many += replaced
            return text
        return node

    rewritten = walk(document, "")
    if not how_many:
        return content, 0
    return json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n", how_many


def erase(
    where_: Everywhere,
    name: str,
    *,
    replacement: str = UNNAMED,
    forget_the_voiceprints: Callable[[str], int] | None = None,
    forget_in_the_index: Callable[[str], int] | None = None,
) -> Erased:
    """Takes the name out of everything, and says what it took it out of.

    The bank and the index are reached through the two callables rather than
    opened here: they are an adapter's business, and this use case has no right
    to know which.
    """
    done = Erased()
    for path, what in _files_of(where_):
        content = _read(path)
        if content is None:
            continue
        if path.suffix == STRUCTURED:
            fresh, how_many = _rewrite_json(content, name, replacement)
        else:
            fresh, how_many = redact(content, name, replacement)
        if not how_many:
            continue
        temporary = path.with_suffix(path.suffix + ".partiel")
        try:
            temporary.write_text(fresh, encoding="utf-8")
            temporary.replace(path)
        except OSError:
            temporary.unlink(missing_ok=True)
            continue
        done.traces.append(Trace(path, what, how_many))
    if forget_the_voiceprints is not None:
        done.voiceprints = forget_the_voiceprints(name)
        if done.voiceprints:
            done.traces.append(Trace(
                Path("banque-de-voix"), "empreintes vocales", done.voiceprints,
                biometric=True,
            ))
    if forget_in_the_index is not None:
        done.index_entries = forget_in_the_index(name)
    done.traces.sort(key=lambda trace: (-trace.occurrences, str(trace.path)))
    return done
