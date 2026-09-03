"""Ce que le métier attend du monde extérieur.

Des `Protocol` et non des classes de base : un adaptateur n'a rien à hériter, il
lui suffit d'avoir la bonne forme. Les doublures de test s'écrivent alors en
trois lignes, sans importer quoi que ce soit d'ici.

Chaque port correspond à une chose qui change d'un système à l'autre ou d'un
outil à l'autre — c'est précisément la liste de ce qu'il faudra réécrire pour
Windows, ou le jour où l'on changera de modèle de transcription.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from greffier.domaine.modeles import Empreinte, Intervalle, Personne, Replique, TourDeParole


@runtime_checkable
class Enregistreur(Protocol):
    """Capture le son de la réunion.

    Le seul port dont l'implémentation diffère vraiment sur les trois systèmes :
    entendre sa propre voix est trivial, réenregistrer ce que les haut-parleurs
    jouent ne l'est pas.
    """

    def demarrer(self, destination: Path) -> int:
        """Lance l'enregistrement en tâche de fond, rend l'identifiant du processus."""
        ...

    def arreter(self, processus: int) -> None:
        """Arrête proprement, en laissant le fichier audio exploitable."""
        ...

    def essayer(self, peripherique: str, secondes: float = 1.5) -> float:
        """Niveau capté par une entrée, en décibels. -120 si elle n'ouvre pas.

        Un micro peut être branché, reconnu, réglé au maximum, et pourtant
        muet : les casques USB ont un bouton de sourdine sur leur boîtier. Le
        choisir sans l'écouter donne une réunion entière de silence, et un
        message d'erreur qui accuse l'autorisation micro.
        """
        ...

    def preparer_transcription(self, audio: Path, destination: Path) -> Path:
        """Met l'enregistrement au niveau qu'attend la transcription.

        Un signal faible ne donne pas une transcription pauvre : il donne une
        transcription **inventée**. Sur un enregistrement réel à -43 dB, whisper
        a rendu « Merci d'avoir regardé cette vidéo ! » là où la personne disait
        « Test, test de réunion ». Le même fichier normalisé rend la bonne
        phrase.

        Chaque canal est mis à niveau séparément avant d'être mélangé : sinon
        une voix 12 dB sous les autres reste 12 dB sous les autres, et c'est
        elle que le modèle invente.
        """
        ...

    def assembler(self, morceaux: list[Path], destination: Path) -> Path:
        """Recolle les morceaux d'un enregistrement en un seul fichier.

        Un enregistrement se coupe en plusieurs morceaux quand le matériel
        change en cours de réunion : brancher un casque impose de reconstruire
        le périphérique de capture, donc de rouvrir un fichier. La suite de la
        chaîne, elle, attend un flux continu — les empreintes vocales se
        comparent mal d'un fichier à l'autre.
        """
        ...

    def niveaux(self, audio: Path) -> list[float]:
        """Niveau moyen de chaque canal, en dB. -120 pour un canal muet."""
        ...


@runtime_checkable
class Transcripteur(Protocol):
    """Transforme de l'audio en répliques horodatées."""

    def transcrire(self, audio: Path, langue: str, amorce: str) -> list[Replique]:
        ...


@runtime_checkable
class Diariseur(Protocol):
    """Découpe l'audio en tours de parole et regroupe les voix."""

    def decouper(self, audio: Path, personnes: int | None) -> list[TourDeParole]:
        ...


@runtime_checkable
class LecteurDeCanaux(Protocol):
    """Dit quels passages d'un enregistrement viennent du micro.

    Le seul port dont la réponse ne vient d'aucun modèle : c'est du câblage. La
    transcription en direct s'en sert pour afficher « Toi » sans consulter la
    moindre empreinte — et sans jamais se tromper.
    """

    def passages_locaux(self, audio: Path) -> list[Intervalle]:
        ...


@runtime_checkable
class ExtracteurEmpreintes(Protocol):
    """Produit la signature vocale d'un extrait."""

    def extraire_intervalles(self, audio: Path, intervalles: list[Intervalle]) -> list[Empreinte]:
        ...


@runtime_checkable
class BanqueDeVoix(Protocol):
    """Mémoire des voix connues, d'une réunion à l'autre."""

    def personnes(self) -> list[Personne]:
        ...

    def enregistrer(self, nom: str, empreinte: Empreinte) -> Personne:
        """Range l'empreinte et rend la personne, enrichie."""
        ...


@runtime_checkable
class Redacteur(Protocol):
    """Rédige le compte rendu à partir de la transcription attribuée."""

    def rediger(self, transcription: str) -> str:
        ...


@runtime_checkable
class Expediteur(Protocol):
    """Envoie le compte rendu."""

    def envoyer(self, destinataire: str, sujet: str, corps: str, pieces: list[Path]) -> None:
        ...


@runtime_checkable
class DepotReunions(Protocol):
    """Garde une réunion traitée, et sait la relire.

    C'est ce qui manquait à la chaîne : l'écriture n'existait que dans la
    commande en ligne, donc une réunion terminée depuis la fenêtre ne laissait
    rien — ni dans la liste des réunions, ni de quoi nommer une voix après coup.
    """

    def enregistrer(self, reunion: Any) -> Path:
        """Écrit le fichier maître et rend son chemin."""
        ...


@runtime_checkable
class Notificateur(Protocol):
    """Prévient l'utilisateur pendant que la chaîne tourne, sans terminal ouvert."""

    def notifier(self, titre: str, message: str) -> None:
        ...


@runtime_checkable
class JournalEtat(Protocol):
    """Publie l'avancement, pour que l'interface sache où en est la chaîne."""

    def publier(self, phase: str, message: str = "") -> None:
        ...
