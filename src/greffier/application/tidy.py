"""Oublier une réunion, et savoir ce que cela efface avant de le faire.

Une réunion ne tient pas dans un fichier : l'audio, la transcription, le compte
rendu, le fil du direct, les propositions de noms et le fichier maître vivent
côte à côte, nommés par le même identifiant. Supprimer le seul fichier maître
laissait 158 Mo d'audio orphelins et un compte rendu que plus rien ne
référençait ; les supprimer sans le dire efface un enregistrement qu'on ne peut
pas refaire.

D'où deux fonctions distinctes : `pieces_de` rassemble et **pèse** ce qui
existe, pour qu'une confirmation dise la vérité, et `oublier` efface. La
première ne touche à rien, ce qui permet à l'interface de demander avant.

Ce module ne connaît aucun outil : il reçoit les dossiers et rend des chemins.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from greffier.domain.retention import Geste, Regle


@dataclass(frozen=True, slots=True)
class Emplacements:
    """Où vivent les morceaux d'une réunion.

    Repris de la configuration par l'appelant plutôt que lu ici : le cas d'usage
    n'a pas à savoir comment les chemins sont réglés.
    """

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
class Piece:
    path: Path
    quoi: str

    @property
    def bytes_read(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

def pieces_de(ou: Emplacements, identifier: str) -> list[Piece]:
    """Tout ce qui existe pour cette réunion, du plus lourd au plus léger.

    L'audio d'abord parce que c'est lui qui pèse, et c'est le seul qu'on ne
    puisse pas reconstituer : la transcription et le compte rendu se refont
    depuis lui, l'inverse est faux.
    """
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
    trouvees = [
        Piece(path, quoi)
        for folder, suffixes, quoi in candidats
        if folder is not None
        for suffixe in suffixes
        if (path := folder / f"{identifier}.{suffixe}").exists()
    ]
    trouvees += [
        Piece(document, f"document fourni ({document.stem})")
        for document in _supplied_documents(ou, identifier)
    ]
    return sorted(trouvees, key=lambda p: -p.bytes_read)

def _supplied_documents(ou: Emplacements, identifier: str) -> list[Path]:
    """Les documents déposés pendant la réunion. Un dossier, pas un fichier."""
    if ou.pieces is None:
        return []
    folder = ou.pieces / identifier
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []

def forget(ou: Emplacements, identifier: str) -> list[Piece]:
    """Efface la réunion, et rend ce qui a été effacé.

    Ce qui résiste est laissé sans faire échouer le reste : un compte rendu
    ouvert dans un éditeur ne doit pas empêcher de libérer l'audio.
    """
    effacees: list[Piece] = []
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
class Rangement:
    """Ce qu'un tour de rangement a fait, ou ferait."""

    identifier: str
    geste: str
    gagne: int = 0
    trouble: str = ""

def audio_de(ou: Emplacements, identifier: str) -> Path | None:
    """L'enregistrement de cette réunion, compressé ou non."""
    for suffixe in ("wav", "opus", "m4a", "mp3"):
        path = ou.recordings / f"{identifier}.{suffixe}"
        if path.exists():
            return path
    return None

def tidy(
    ou: Emplacements,
    regle: Regle,
    meetings: Sequence[tuple[str, float, bool]],
    compresser: Callable[[Path], Path],
    for_real: bool = False,
) -> list[Rangement]:
    """Applique la règle de rétention, ou dit seulement ce qu'elle ferait.

    `reunions` porte, pour chacune, son identifiant, son âge en jours et si elle
    est transcrite. Le calcul de l'âge appartient à l'appelant : il dépend de ce
    que le fichier maître sait de la réunion, pas de cette fonction.

    `pour_de_vrai` à faux est le défaut, et c'est délibéré : on doit pouvoir
    montrer ce qu'un rangement emporterait avant de le lancer. Effacer un
    enregistrement ne se rattrape pas.
    """
    faits: list[Rangement] = []
    for identifier, jours, transcrite in meetings:
        audio = audio_de(ou, identifier)
        if audio is None:
            continue
        geste = regle.decide(jours, transcrite, audio.suffix == ".opus")
        if geste is Geste.RIEN:
            continue
        avant = audio.stat().st_size if audio.exists() else 0
        if not for_real:
            gagne = avant if geste is Geste.EFFACER else int(avant * 0.9)
            faits.append(Rangement(identifier, str(geste), gagne))
            continue
        try:
            if geste is Geste.EFFACER:
                audio.unlink()
                faits.append(Rangement(identifier, str(geste), avant))
            else:
                produit = compresser(audio)
                apres = produit.stat().st_size if produit.exists() else 0
                faits.append(Rangement(identifier, str(geste), max(0, avant - apres)))
        except (OSError, RuntimeError) as trouble:
            faits.append(Rangement(identifier, str(geste), 0, str(trouble)))
    return faits

def readable(bytes_read: int) -> str:
    """« 151 Mo », « 34 Ko » — pour une phrase de confirmation."""
    if bytes_read >= 1024**3:
        return f"{bytes_read / 1024**3:.1f} Go"
    if bytes_read >= 1024**2:
        return f"{bytes_read / 1024**2:.0f} Mo"
    if bytes_read >= 1024:
        return f"{bytes_read / 1024:.0f} Ko"
    return f"{bytes_read} o"
