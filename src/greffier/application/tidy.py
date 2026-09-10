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

def pieces_de(ou: Places, identifier: str) -> list[Attachment]:
    """Everything that exists for this meeting, heaviest first."""
    candidats = [
        (ou.recordings, ("wav", "opus", "m4a", "mp3"), "enregistrement audio"),
        (ou.meetings, ("json",), "réunion transcrite"),
        (ou.transcripts, ("txt",), "transcription lisible"),
        (ou.minutes_folder, ("md",), "compte rendu"),
        (ou.live, ("jsonl",), "fil du direct"),
        (ou.propositions, ("jsonl",), "propositions de noms"),
        (ou.questions, ("jsonl",), "questions posées"),
        (ou.conversations, ("jsonl",), "conversation avec l'assistant"),
    ]
    found = [
        Attachment(path, what)
        for folder, suffixes, what in candidats
        if folder is not None
        for suffixe in suffixes
        if (path := folder / f"{identifier}.{suffixe}").exists()
    ]
    found += [
        Attachment(document, f"document fourni ({document.stem})")
        for document in _supplied_documents(ou, identifier)
    ]
    return sorted(found, key=lambda p: -p.bytes_read)

def _supplied_documents(ou: Places, identifier: str) -> list[Path]:
    """The documents dropped during the meeting."""
    if ou.pieces is None:
        return []
    folder = ou.pieces / identifier
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []

def forget(ou: Places, identifier: str) -> list[Attachment]:
    """Erases the meeting, and returns what was erased."""
    effacees: list[Attachment] = []
    for piece in pieces_de(ou, identifier):
        try:
            piece.path.unlink()
        except OSError:
            continue
        effacees.append(piece)
    if ou.pieces is not None:
        with contextlib.suppress(OSError):
            (ou.pieces / identifier).rmdir()
    return effacees

@dataclass(frozen=True, slots=True)
class Tidying:
    """What a tidying pass did, or would do."""

    identifier: str
    geste: str
    gagne: int = 0
    trouble: str = ""

def audio_de(ou: Places, identifier: str) -> Path | None:
    """This meeting's recording, compressed or not."""
    for suffixe in ("wav", "opus", "m4a", "mp3"):
        path = ou.recordings / f"{identifier}.{suffixe}"
        if path.exists():
            return path
    return None

def tidy(
    ou: Places,
    regle: Rule,
    meetings: Sequence[tuple[str, float, bool]],
    compresser: Callable[[Path], Path],
    for_real: bool = False,
) -> list[Tidying]:
    """Applies the retention rule, or only says what it would do."""
    faits: list[Tidying] = []
    for identifier, jours, transcrite in meetings:
        audio = audio_de(ou, identifier)
        if audio is None:
            continue
        geste = regle.decide(jours, transcrite, audio.suffix == ".opus")
        if geste is Gesture.NOTHING:
            continue
        avant = audio.stat().st_size if audio.exists() else 0
        if not for_real:
            gagne = avant if geste is Gesture.EFFACER else int(avant * 0.9)
            faits.append(Tidying(identifier, str(geste), gagne))
            continue
        try:
            if geste is Gesture.EFFACER:
                audio.unlink()
                faits.append(Tidying(identifier, str(geste), avant))
            else:
                produit = compresser(audio)
                apres = produit.stat().st_size if produit.exists() else 0
                faits.append(Tidying(identifier, str(geste), max(0, avant - apres)))
        except (OSError, RuntimeError) as trouble:
            faits.append(Tidying(identifier, str(geste), 0, str(trouble)))
    return faits

def readable(bytes_read: int) -> str:
    """"151 MB", "34 kB" — for a sentence a person reads."""
    if bytes_read >= 1024**3:
        return f"{bytes_read / 1024**3:.1f} Go"
    if bytes_read >= 1024**2:
        return f"{bytes_read / 1024**2:.0f} Mo"
    if bytes_read >= 1024:
        return f"{bytes_read / 1024:.0f} Ko"
    return f"{bytes_read} o"
