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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from greffier.domaine.retention import Geste, Regle


@dataclass(frozen=True, slots=True)
class Emplacements:
    """Où vivent les morceaux d'une réunion.

    Repris de la configuration par l'appelant plutôt que lu ici : le cas d'usage
    n'a pas à savoir comment les chemins sont réglés.
    """

    reunions: Path
    enregistrements: Path
    transcriptions: Path
    comptes_rendus: Path
    direct: Path
    propositions: Path


@dataclass(frozen=True, slots=True)
class Piece:
    chemin: Path
    #: Ce que la pièce est, dit à qui va confirmer : « enregistrement audio »
    #: pèse autrement que « propositions de noms ».
    quoi: str

    @property
    def octets(self) -> int:
        try:
            return self.chemin.stat().st_size
        except OSError:
            return 0


def pieces_de(ou: Emplacements, identifiant: str) -> list[Piece]:
    """Tout ce qui existe pour cette réunion, du plus lourd au plus léger.

    L'audio d'abord parce que c'est lui qui pèse, et c'est le seul qu'on ne
    puisse pas reconstituer : la transcription et le compte rendu se refont
    depuis lui, l'inverse est faux.
    """
    candidats = [
        (ou.enregistrements, ("wav", "opus", "m4a", "mp3"), "enregistrement audio"),
        (ou.reunions, ("json",), "réunion transcrite"),
        (ou.transcriptions, ("txt",), "transcription lisible"),
        (ou.comptes_rendus, ("md",), "compte rendu"),
        (ou.direct, ("jsonl",), "fil du direct"),
        (ou.propositions, ("jsonl",), "propositions de noms"),
    ]
    trouvees = [
        Piece(chemin, quoi)
        for dossier, suffixes, quoi in candidats
        for suffixe in suffixes
        if (chemin := dossier / f"{identifiant}.{suffixe}").exists()
    ]
    return sorted(trouvees, key=lambda p: -p.octets)


def oublier(ou: Emplacements, identifiant: str) -> list[Piece]:
    """Efface la réunion, et rend ce qui a été effacé.

    Ce qui résiste est laissé sans faire échouer le reste : un compte rendu
    ouvert dans un éditeur ne doit pas empêcher de libérer l'audio.
    """
    effacees: list[Piece] = []
    for piece in pieces_de(ou, identifiant):
        try:
            piece.chemin.unlink()
        except OSError:
            continue
        effacees.append(piece)
    return effacees


@dataclass(frozen=True, slots=True)
class Rangement:
    """Ce qu'un tour de rangement a fait, ou ferait."""

    identifiant: str
    geste: str
    #: Octets libérés — ou qui le seraient, quand on ne fait que constater.
    gagne: int = 0
    souci: str = ""


def audio_de(ou: Emplacements, identifiant: str) -> Path | None:
    """L'enregistrement de cette réunion, compressé ou non."""
    for suffixe in ("wav", "opus", "m4a", "mp3"):
        chemin = ou.enregistrements / f"{identifiant}.{suffixe}"
        if chemin.exists():
            return chemin
    return None


def ranger(
    ou: Emplacements,
    regle: Regle,
    reunions: Sequence[tuple[str, float, bool]],
    compresser: Callable[[Path], Path],
    pour_de_vrai: bool = False,
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
    for identifiant, jours, transcrite in reunions:
        audio = audio_de(ou, identifiant)
        if audio is None:
            continue
        geste = regle.decider(jours, transcrite, audio.suffix == ".opus")
        if geste is Geste.RIEN:
            continue
        avant = audio.stat().st_size if audio.exists() else 0
        if not pour_de_vrai:
            # Ce que la compression gagnerait n'est pas mesurable sans la faire :
            # on annonce l'ordre de grandeur mesuré, sans le présenter comme un
            # chiffre exact.
            gagne = avant if geste is Geste.EFFACER else int(avant * 0.9)
            faits.append(Rangement(identifiant, str(geste), gagne))
            continue
        try:
            if geste is Geste.EFFACER:
                audio.unlink()
                faits.append(Rangement(identifiant, str(geste), avant))
            else:
                produit = compresser(audio)
                apres = produit.stat().st_size if produit.exists() else 0
                faits.append(Rangement(identifiant, str(geste), max(0, avant - apres)))
        except (OSError, RuntimeError) as souci:
            faits.append(Rangement(identifiant, str(geste), 0, str(souci)))
    return faits


def lisible(octets: int) -> str:
    """« 151 Mo », « 34 Ko » — pour une phrase de confirmation."""
    if octets >= 1024**3:
        return f"{octets / 1024**3:.1f} Go"
    if octets >= 1024**2:
        return f"{octets / 1024**2:.0f} Mo"
    if octets >= 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets} o"
