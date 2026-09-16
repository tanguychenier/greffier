"""Forgetting a meeting, and knowing what that erases before doing it."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from greffier.domain.retention import Gesture, Rule


@dataclass(frozen=True, slots=True)
class Places:
    """Where the pieces of a meeting live."""

    meetings: Path
    recordings: Path
    transcripts: Path
    minutes_folder: Path
    live: Path
    propositions: Path
    questions: Path | None = None
    conversations: Path | None = None
    pieces: Path | None = None

@dataclass(frozen=True, slots=True)
class Attachment:
    path: Path
    what: str

    @property
    def bytes_read(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

def pieces_de(where_: Places, identifier: str) -> list[Attachment]:
    """Everything that exists for this meeting, heaviest first."""
    candidates_ = [
        (where_.recordings, ("wav", "opus", "m4a", "mp3"), "enregistrement audio"),
        (where_.meetings, ("json",), "réunion transcrite"),
        (where_.transcripts, ("txt",), "transcription lisible"),
        (where_.minutes_folder, ("md",), "compte rendu"),
        (where_.live, ("jsonl",), "fil du direct"),
        (where_.propositions, ("jsonl",), "propositions de noms"),
        (where_.questions, ("jsonl",), "questions posées"),
        (where_.conversations, ("jsonl",), "conversation avec l'assistant"),
    ]
    found = [
        Attachment(path, what)
        for folder, suffixes, what in candidates_
        if folder is not None
        for the_suffix in suffixes
        if (path := folder / f"{identifier}.{the_suffix}").exists()
    ]
    found += [
        Attachment(document, f"document fourni ({document.stem})")
        for document in _supplied_documents(where_, identifier)
    ]
    return sorted(found, key=lambda p: -p.bytes_read)

def _supplied_documents(where_: Places, identifier: str) -> list[Path]:
    """The documents dropped during the meeting."""
    if where_.pieces is None:
        return []
    folder = where_.pieces / identifier
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []

def forget(where_: Places, identifier: str) -> list[Attachment]:
    """Erases the meeting, and returns what was erased."""
    erased: list[Attachment] = []
    for piece in pieces_de(where_, identifier):
        try:
            piece.path.unlink()
        except OSError:
            continue
        erased.append(piece)
    if where_.pieces is not None:
        with contextlib.suppress(OSError):
            (where_.pieces / identifier).rmdir()
    return erased

@dataclass(frozen=True, slots=True)
class Tidying:
    """What a tidying pass did, or would do."""

    identifier: str
    the_gesture: str
    gained: int = 0
    trouble: str = ""

def audio_de(where_: Places, identifier: str) -> Path | None:
    """This meeting's recording, compressed or not."""
    for the_suffix in ("wav", "opus", "m4a", "mp3"):
        path = where_.recordings / f"{identifier}.{the_suffix}"
        if path.exists():
            return path
    return None

def tidy(
    where_: Places,
    rule: Rule,
    meetings: Sequence[tuple[str, float, bool]],
    compress: Callable[[Path], Path],
    for_real: bool = False,
) -> list[Tidying]:
    """Applies the retention rule, or only says what it would do."""
    done_ones: list[Tidying] = []
    for identifier, days, is_transcribed in meetings:
        audio = audio_de(where_, identifier)
        if audio is None:
            continue
        the_gesture = rule.decide(days, is_transcribed, audio.suffix == ".opus")
        if the_gesture is Gesture.NOTHING:
            continue
        earlier = audio.stat().st_size if audio.exists() else 0
        if not for_real:
            gained = earlier if the_gesture is Gesture.ERASE else int(earlier * 0.9)
            done_ones.append(Tidying(identifier, str(the_gesture), gained))
            continue
        try:
            if the_gesture is Gesture.ERASE:
                audio.unlink()
                done_ones.append(Tidying(identifier, str(the_gesture), earlier))
            else:
                product = compress(audio)
                later = product.stat().st_size if product.exists() else 0
                done_ones.append(Tidying(identifier, str(the_gesture), max(0, earlier - later)))
        except (OSError, RuntimeError) as trouble:
            done_ones.append(Tidying(identifier, str(the_gesture), 0, str(trouble)))
    return done_ones

def readable(bytes_read: int) -> str:
    """"151 MB", "34 kB", for a sentence a person reads."""
    if bytes_read >= 1024**3:
        return f"{bytes_read / 1024**3:.1f} Go"
    if bytes_read >= 1024**2:
        return f"{bytes_read / 1024**2:.0f} Mo"
    if bytes_read >= 1024:
        return f"{bytes_read / 1024:.0f} Ko"
    return f"{bytes_read} o"
