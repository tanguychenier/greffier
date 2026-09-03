"""La machine à états d'un enregistrement.

Deux commandes séparées dans le temps — on démarre, on part en réunion, on
revient une heure plus tard et on arrête — donc deux processus différents. L'état
ne peut pas vivre en mémoire : il est sur le disque, et c'est le système
d'exploitation qui arbitre, via l'existence d'un processus vivant.

Ce fichier d'état sert aussi d'interface : une icône de barre de menus ou de
zone de notification n'a qu'à le lire pour afficher où en est la chaîne.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from greffier.domaine.modeles import Phase
from greffier.ports import sortants


def _identifiant(nom: str, horodatage: datetime) -> str:
    """Nom de fichier lisible et triable : la date d'abord, puis le sujet."""
    depouille = unicodedata.normalize("NFD", nom)
    sans_accent = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    reduit = re.sub(r"[^a-zA-Z0-9]+", "-", sans_accent).strip("-").lower() or "reunion"
    return f"{horodatage:%Y-%m-%d_%Hh%M}_{reduit}"


def _tuer_arbre(pid: int) -> None:
    """Arrête un processus et sa descendance.

    whisper est un petit-enfant : tuer le seul parent laisserait le modèle
    tourner pour rien, sur toute la durée d'une réunion.
    """
    import signal
    import subprocess

    try:
        enfants = subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        enfants = []
    for enfant in enfants:
        _tuer_arbre(int(enfant))
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.kill(pid, signal.SIGTERM)


def _vivant(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        # PermissionError : le processus existe mais appartient à quelqu'un
        # d'autre — donc ce n'est pas le nôtre, il ne compte pas.
        return False
    return True


@dataclass
class Etat:
    """Ce que l'interface a besoin de savoir, sans rien calculer."""

    phase: Phase = Phase.REPOS
    message: str = ""
    nom: str = ""
    identifiant: str = ""
    audio: Path | None = None
    debut: datetime | None = None
    pid: int | None = None
    #: Morceaux capturés jusqu'ici. Plusieurs dès que le matériel a changé en
    #: cours de réunion : chaque changement impose de rouvrir un fichier.
    morceaux: list[Path] = field(default_factory=list)
    #: Ce que la veille a constaté du matériel, pour le dire au compte rendu.
    evenements: list[str] = field(default_factory=list)
    #: Depuis quand l'enregistrement est suspendu, s'il l'est.
    suspendu_le: datetime | None = None
    #: Temps passé en pause, retiré de la durée affichée.
    pause_totale: float = 0.0
    #: Sortie système d'avant la réunion, à rendre une fois celle-ci finie.
    sortie_precedente: str = ""

    @property
    def secondes(self) -> float:
        """Durée réellement enregistrée, pauses déduites."""
        if self.debut is None:
            return 0.0
        ecoule = (datetime.now(UTC) - self.debut).total_seconds() - self.pause_totale
        if self.suspendu_le is not None:
            ecoule -= (datetime.now(UTC) - self.suspendu_le).total_seconds()
        return max(0.0, ecoule)


class Enregistrement:
    """Démarre, arrête, et sait dire où on en est.

    L'état est réécrit de façon atomique : une interface qui le lit en boucle ne
    doit jamais tomber sur une version à moitié écrite.
    """

    def __init__(
        self,
        enregistreur: sortants.Enregistreur,
        dossier_audio: Path,
        fichier_etat: Path,
    ) -> None:
        self.enregistreur = enregistreur
        self.dossier_audio = dossier_audio
        self.fichier_etat = fichier_etat

    # ----------------------------------------------------------------- état

    def lire(self) -> Etat:
        if not self.fichier_etat.exists():
            return Etat()
        try:
            contenu = json.loads(self.fichier_etat.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return Etat()
        etat = Etat(
            phase=Phase(contenu.get("phase", Phase.REPOS.value)),
            message=contenu.get("message", ""),
            nom=contenu.get("nom", ""),
            identifiant=contenu.get("identifiant", ""),
            audio=Path(contenu["audio"]) if contenu.get("audio") else None,
            debut=datetime.fromisoformat(contenu["debut"]) if contenu.get("debut") else None,
            pid=contenu.get("pid"),
            morceaux=[Path(x) for x in contenu.get("morceaux", [])],
            evenements=list(contenu.get("evenements", [])),
            suspendu_le=(
                datetime.fromisoformat(contenu["suspendu_le"])
                if contenu.get("suspendu_le") else None
            ),
            pause_totale=float(contenu.get("pause_totale", 0.0)),
            sortie_precedente=contenu.get("sortie_precedente", ""),
        )
        # Le fichier survit à un redémarrage : c'est la présence du processus
        # qui décide si un enregistrement est vraiment en cours.
        if etat.phase is Phase.ENREGISTREMENT and not _vivant(etat.pid):
            etat.phase = Phase.ECHEC
            etat.message = "Enregistrement interrompu (redémarrage ?). L'audio est conservé."
        return etat

    def ecrire(self, etat: Etat) -> None:
        self.fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        contenu = {
            "phase": etat.phase.value,
            "message": etat.message,
            "nom": etat.nom,
            "identifiant": etat.identifiant,
            "audio": str(etat.audio) if etat.audio else "",
            "debut": etat.debut.isoformat() if etat.debut else "",
            "pid": etat.pid,
            "morceaux": [str(x) for x in etat.morceaux],
            "evenements": etat.evenements,
            "suspendu_le": etat.suspendu_le.isoformat() if etat.suspendu_le else "",
            "pause_totale": etat.pause_totale,
            "sortie_precedente": etat.sortie_precedente,
        }
        provisoire = self.fichier_etat.with_suffix(".json.partiel")
        provisoire.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
        provisoire.replace(self.fichier_etat)

    def publier(self, phase: str, message: str = "") -> None:
        """Sert de `JournalEtat` : la chaîne de traitement publie ici aussi.

        Le processus courant est retenu : c'est lui qui porte la transcription
        puis la rédaction, et c'est donc lui qu'il faut interrompre si
        l'utilisateur change d'avis pendant les longues minutes de traitement.
        """
        etat = self.lire()
        etat.phase = Phase(phase)
        etat.message = message
        etat.pid = os.getpid()
        self.ecrire(etat)

    def interrompre(self) -> Etat:
        """Arrête le traitement en cours. L'audio, lui, est conservé."""
        etat = self.lire()
        pid = etat.pid
        if not etat.phase.en_cours or not _vivant(pid) or pid is None:
            raise RuntimeError("Aucun traitement en cours.")
        _tuer_arbre(pid)
        etat.phase = Phase.INTERROMPU
        etat.message = "Traitement interrompu. L'audio est conservé."
        etat.pid = None
        self.ecrire(etat)
        return etat

    def suspendre(self) -> Etat:
        """Suspend l'enregistrement sans clore la réunion.

        On arrête la capture, proprement, et on garde le morceau. Reprendre en
        ouvrira un suivant : c'est exactement ce que fait un changement de
        matériel, et le recollage à l'arrêt ne voit pas la différence.

        Utile en réunion : une interruption, un aparté, une pause déjeuner. Sans
        cela, il fallait tout arrêter, donc lancer le traitement, puis relancer
        une seconde réunion et se retrouver avec deux comptes rendus.
        """
        etat = self.lire()
        if etat.phase is not Phase.ENREGISTREMENT:
            raise RuntimeError("Aucun enregistrement en cours.")
        if etat.pid is not None and _vivant(etat.pid):
            self.enregistreur.arreter(etat.pid)
        etat.phase = Phase.PAUSE
        etat.pid = None
        etat.message = "En pause. Ce qui a été capté est conservé."
        etat.suspendu_le = datetime.now(UTC)
        self.ecrire(etat)
        return etat

    def relancer(self) -> Etat:
        """Repart après une pause, sur un morceau de plus."""
        etat = self.lire()
        if etat.phase is not Phase.PAUSE:
            raise RuntimeError("L'enregistrement n'est pas en pause.")
        suivant = self.dossier_audio / f"{etat.identifiant}-{len(etat.morceaux) + 1:02d}.wav"
        etat.pid = self.enregistreur.demarrer(suivant)
        etat.morceaux.append(suivant)
        etat.phase = Phase.ENREGISTREMENT
        etat.message = "Enregistrement en cours."
        # Le temps de pause ne compte pas dans la durée de la réunion.
        if etat.suspendu_le is not None:
            etat.pause_totale += (datetime.now(UTC) - etat.suspendu_le).total_seconds()
            etat.suspendu_le = None
        self.ecrire(etat)
        return etat

    def reprendre(self, raison: str) -> Etat:
        """Clôt le morceau courant et repart sur le suivant.

        Appelée quand le matériel a changé : le périphérique agrégé vient d'être
        reconstruit, et ffmpeg tient encore l'ancien. On l'arrête proprement, ce
        qui laisse un fichier relisible, puis on rouvre.

        Le trou entre les deux est de l'ordre de la seconde. C'est le prix d'un
        branchement en cours de réunion, et il se compare mal à celui d'une voix
        absente du compte rendu.
        """
        etat = self.lire()
        if etat.phase is not Phase.ENREGISTREMENT or etat.audio is None:
            raise RuntimeError("Aucun enregistrement en cours.")
        if etat.pid is not None and _vivant(etat.pid):
            self.enregistreur.arreter(etat.pid)
        suivant = self.dossier_audio / f"{etat.identifiant}-{len(etat.morceaux) + 1:02d}.wav"
        etat.pid = self.enregistreur.demarrer(suivant)
        etat.morceaux.append(suivant)
        etat.evenements.append(raison)
        etat.message = raison
        self.ecrire(etat)
        return etat

    def signaler(self, avertissement: str) -> Etat:
        """Note un constat sur le matériel sans toucher à la capture."""
        etat = self.lire()
        etat.evenements.append(avertissement)
        etat.message = avertissement
        self.ecrire(etat)
        return etat

    # ------------------------------------------------------------- actions

    def demarrer(self, nom: str = "reunion", sortie_precedente: str = "") -> Etat:
        en_cours = self.lire()
        if en_cours.phase is Phase.ENREGISTREMENT:
            raise RuntimeError(
                f"Un enregistrement est déjà en cours depuis "
                f"{en_cours.secondes / 60:.0f} min. « greffier arreter » d'abord."
            )
        horodatage = datetime.now(UTC).astimezone()
        identifiant = _identifiant(nom, horodatage)
        audio = self.dossier_audio / f"{identifiant}.wav"
        premier = self.dossier_audio / f"{identifiant}-01.wav"
        pid = self.enregistreur.demarrer(premier)
        etat = Etat(
            phase=Phase.ENREGISTREMENT, nom=nom, identifiant=identifiant,
            audio=audio, debut=datetime.now(UTC), pid=pid,
            morceaux=[premier],
            sortie_precedente=sortie_precedente,
            message="Enregistrement en cours.",
        )
        self.ecrire(etat)
        return etat

    def arreter(self) -> Etat:
        etat = self.lire()
        if etat.audio is None:
            raise RuntimeError("Aucun enregistrement à arrêter.")
        # Arrêter depuis la pause est légitime : la réunion est finie, la
        # capture était simplement suspendue.
        if etat.pid is not None and _vivant(etat.pid):
            self.enregistreur.arreter(etat.pid)
        etat.phase = Phase.FINALISATION
        etat.message = "Enregistrement arrêté."
        etat.pid = None
        self.ecrire(etat)
        # Le garde-fou passe avant le recollage : sinon le fichier recollé
        # remplace celui qu'on vient de trouver vide, et plus rien ne signale
        # qu'aucun son n'a été capté.
        morceaux = [m for m in (etat.morceaux or [etat.audio]) if m is not None]
        utiles = [m for m in morceaux if m.exists() and m.stat().st_size > 0]
        if not utiles:
            raise RuntimeError(
                f"{etat.audio} est vide. Vérifie l'autorisation micro et le "
                "périphérique d'entrée."
            )
        # La suite de la chaîne attend un flux continu : les empreintes vocales
        # se comparent mal d'un fichier à l'autre.
        if len(utiles) > 1:
            etat.message = f"Enregistrement arrêté, {len(utiles)} morceaux recollés."
        self.enregistreur.assembler(utiles, etat.audio)
        for morceau in morceaux:
            if morceau != etat.audio:
                morceau.unlink(missing_ok=True)
        etat.morceaux = [etat.audio]
        self.ecrire(etat)
        return etat
