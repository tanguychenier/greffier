"""Reconnaître ce qu'un fichier déposé est, et ce qu'on peut en faire.

Déposer un fichier sur l'outil ne dit pas ce qu'il faut en faire. Un
enregistrement Teams est une réunion à transcrire ; un compte rendu écrit par
un collègue est du contexte ; un export de tickets n'est ni l'un ni l'autre.
Traiter tout de la même façon produirait un fourre-tout qui n'organise rien —
ce qui est exactement le contraire de ce qu'on demande à l'outil.

D'où une **proposition**, jamais une décision : le classement s'affiche, et
c'est un humain qui valide. Une vidéo de deux heures mal classée coûte une
transcription pour rien ; un document classé en réunion produit un compte rendu
d'un texte que personne n'a prononcé.

Ce module ne lit aucun fichier : il regarde un nom et une taille, et propose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Destination(StrEnum):
    """Ce qu'on peut faire d'un fichier déposé."""

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
    """Ce qu'on propose de faire d'un fichier, et pourquoi."""

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
    outils: frozenset[str] = frozenset(),
) -> Suggestion:
    """Ce qu'on propose de faire de ce fichier.

    `outils` porte les commandes disponibles sur le poste — « ffmpeg »,
    « pdftotext », « textutil ». Un destin qui en réclame une absente est
    proposé quand même, avec ce qui manque : dire « il faudrait ffmpeg » est
    plus utile que faire disparaître le fichier de la liste.
    """
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
            bloque_par="" if "ffmpeg" in outils else "ffmpeg est introuvable",
        )

    if suffixe in TEXTS:
        return Suggestion(file, Destination.CONTEXT, "texte lisible tel quel")

    if suffixe in TEXTES_OUTILLES:
        besoin = "pdftotext" if suffixe == ".pdf" else "textutil"
        return Suggestion(
            file, Destination.CONTEXT,
            f"document {suffixe.lstrip('.')} : son texte sera extrait",
            bloque_par="" if besoin in outils else f"{besoin} est introuvable",
        )

    return Suggestion(
        file, Destination.INCONNU,
        f"« {suffixe or 'sans extension'} » n'est ni un son, ni une vidéo, "
        "ni un document texte",
    )

def summarise(propositions: list[Suggestion]) -> str:
    """Une phrase qui dit ce que le lot va devenir, avant validation."""
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
