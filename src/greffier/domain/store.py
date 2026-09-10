"""Recognising what a dropped file is, and what can be done with it."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Destination(StrEnum):
    """What can be done with a dropped file."""

    MEETING = "réunion"
    VIDEO = "vidéo"
    CONTEXT = "contexte"
    UNKNOWN = "inconnu"

SOUNDS = frozenset({".wav", ".mp3", ".m4a", ".opus", ".flac", ".aac", ".aiff", ".ogg"})

VIDEOS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})

TEXTS = frozenset({".txt", ".md", ".markdown"})
TOOLED_TEXTS = frozenset({".pdf", ".doc", ".docx", ".rtf", ".odt"})

MINIMUM_SOUND_SIZE = 200_000

@dataclass(frozen=True, slots=True)
class Suggestion:
    """What is proposed for a file, and why."""

    file: Path
    destination: Destination
    because: str
    blocked_by: str = ""

    @property
    def feasible(self) -> bool:
        return self.destination is not Destination.UNKNOWN and not self.blocked_by

def offer(
    file: Path,
    taille: int | None = None,
    tools: frozenset[str] = frozenset(),
) -> Suggestion:
    """What is proposed for this file."""
    suffixe = file.suffix.casefold()

    if suffixe in SOUNDS:
        if taille is not None and taille < MINIMUM_SOUND_SIZE:
            return Suggestion(
                file, Destination.UNKNOWN,
                f"son trop court pour une réunion ({taille / 1024:.0f} Ko)",
            )
        return Suggestion(file, Destination.MEETING, "enregistrement sonore")

    if suffixe in VIDEOS:
        return Suggestion(
            file, Destination.VIDEO,
            "vidéo : la piste sonore sera extraite, l'image ne sert à rien ici",
            blocked_by="" if "ffmpeg" in tools else "ffmpeg est introuvable",
        )

    if suffixe in TEXTS:
        return Suggestion(file, Destination.CONTEXT, "texte lisible tel quel")

    if suffixe in TOOLED_TEXTS:
        besoin = "pdftotext" if suffixe == ".pdf" else "textutil"
        return Suggestion(
            file, Destination.CONTEXT,
            f"document {suffixe.lstrip('.')} : son texte sera extrait",
            blocked_by="" if besoin in tools else f"{besoin} est introuvable",
        )

    return Suggestion(
        file, Destination.UNKNOWN,
        f"« {suffixe or 'sans extension'} » n'est ni un son, ni une vidéo, "
        "ni un document texte",
    )

def _plural(destination: Destination, how_many: int) -> str:
    """The mark that turns « réunion » into « réunions », never « contextes »."""
    return "s" if how_many > 1 and destination is not Destination.CONTEXT else ""

def summarise(propositions: list[Suggestion]) -> str:
    """A sentence saying what the batch will become, before approval."""
    if not propositions:
        return "Aucun fichier."
    by_destination: dict[Destination, int] = {}
    for proposition in propositions:
        ou = proposition.destination
        by_destination[ou] = by_destination.get(ou, 0) + 1
    chunks = [
        f"{how_many} {destination}{_plural(destination, how_many)}"
        for destination, how_many in by_destination.items()
    ]
    blocked = sum(1 for p in propositions if p.blocked_by)
    sentence = ", ".join(chunks)
    return sentence + (f" — dont {blocked} en attente d'un outil" if blocked else "")
