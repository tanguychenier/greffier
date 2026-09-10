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
    INCONNU = "inconnu"

SONS = frozenset({".wav", ".mp3", ".m4a", ".opus", ".flac", ".aac", ".aiff", ".ogg"})

VIDEOS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})

TEXTS = frozenset({".txt", ".md", ".markdown"})
TEXTES_OUTILLES = frozenset({".pdf", ".doc", ".docx", ".rtf", ".odt"})

TAILLE_MINIMALE_SON = 200_000

@dataclass(frozen=True, slots=True)
class Suggestion:
    """What is proposed for a file, and why."""

    file: Path
    destin: Destination
    parce_que: str
    bloque_par: str = ""

    @property
    def feasible(self) -> bool:
        return self.destin is not Destination.INCONNU and not self.bloque_par

def offer(
    file: Path,
    taille: int | None = None,
    tools: frozenset[str] = frozenset(),
) -> Suggestion:
    """What is proposed for this file."""
    suffixe = file.suffix.casefold()

    if suffixe in SONS:
        if taille is not None and taille < TAILLE_MINIMALE_SON:
            return Suggestion(
                file, Destination.INCONNU,
                f"son trop court pour une réunion ({taille / 1024:.0f} Ko)",
            )
        return Suggestion(file, Destination.MEETING, "enregistrement sonore")

    if suffixe in VIDEOS:
        return Suggestion(
            file, Destination.VIDEO,
            "vidéo : la piste sonore sera extraite, l'image ne sert à rien ici",
            bloque_par="" if "ffmpeg" in tools else "ffmpeg est introuvable",
        )

    if suffixe in TEXTS:
        return Suggestion(file, Destination.CONTEXT, "texte lisible tel quel")

    if suffixe in TEXTES_OUTILLES:
        besoin = "pdftotext" if suffixe == ".pdf" else "textutil"
        return Suggestion(
            file, Destination.CONTEXT,
            f"document {suffixe.lstrip('.')} : son texte sera extrait",
            bloque_par="" if besoin in tools else f"{besoin} est introuvable",
        )

    return Suggestion(
        file, Destination.INCONNU,
        f"« {suffixe or 'sans extension'} » n'est ni un son, ni une vidéo, "
        "ni un document texte",
    )

def summarise(propositions: list[Suggestion]) -> str:
    """A sentence saying what the batch will become, before approval."""
    if not propositions:
        return "Aucun fichier."
    par_destin: dict[Destination, int] = {}
    for proposition in propositions:
        par_destin[proposition.destin] = par_destin.get(proposition.destin, 0) + 1
    chunks = [
        f"{combien} {destin}{'s' if combien > 1 and destin is not Destination.CONTEXT else ''}"
        for destin, combien in par_destin.items()
    ]
    bloques = sum(1 for p in propositions if p.bloque_par)
    phrase = ", ".join(chunks)
    return phrase + (f" — dont {bloques} en attente d'un outil" if bloques else "")
