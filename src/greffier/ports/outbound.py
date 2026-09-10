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
from typing import Protocol, runtime_checkable

from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Person, Span, SpeakerTurn, Utterance, Voiceprint


@runtime_checkable
class AudioRecorder(Protocol):
    """Capture le son de la réunion.

    Le seul port dont l'implémentation diffère vraiment sur les trois systèmes :
    entendre sa propre voix est trivial, réenregistrer ce que les haut-parleurs
    jouent ne l'est pas.
    """

    def start_recording(self, destination: Path) -> int:
        """Lance l'enregistrement en tâche de fond, rend l'identifiant du processus."""
        ...

    def stop_recording(self, processus: int) -> None:
        """Arrête proprement, en laissant le fichier audio exploitable."""
        ...

    def try_it(self, peripherique: str, seconds: float = 1.5) -> float:
        """Niveau capté par une entrée, en décibels. -120 si elle n'ouvre pas.

        Un micro peut être branché, reconnu, réglé au maximum, et pourtant
        muet : les casques USB ont un bouton de sourdine sur leur boîtier. Le
        choisir sans l'écouter donne une réunion entière de silence, et un
        message d'erreur qui accuse l'autorisation micro.
        """
        ...

    def prepare_transcript(self, audio: Path, destination: Path) -> Path:
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

    def wire_up(self, chunks: list[Path], destination: Path) -> Path:
        """Recolle les morceaux d'un enregistrement en un seul fichier.

        Un enregistrement se coupe en plusieurs morceaux quand le matériel
        change en cours de réunion : brancher un casque impose de reconstruire
        le périphérique de capture, donc de rouvrir un fichier. La suite de la
        chaîne, elle, attend un flux continu — les empreintes vocales se
        comparent mal d'un fichier à l'autre.
        """
        ...

    def levels(self, audio: Path) -> list[float]:
        """Niveau moyen de chaque canal, en dB. -120 pour un canal muet."""
        ...


@runtime_checkable
class Transcriber(Protocol):
    """Transforme de l'audio en répliques horodatées."""

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        ...


@runtime_checkable
class Diariser(Protocol):
    """Découpe l'audio en tours de parole et regroupe les voix."""

    def segment(self, audio: Path, people: int | None) -> list[SpeakerTurn]:
        ...


@runtime_checkable
class ChannelReader(Protocol):
    """Dit quels passages d'un enregistrement viennent du micro.

    Le seul port dont la réponse ne vient d'aucun modèle : c'est du câblage. La
    transcription en direct s'en sert pour afficher « Toi » sans consulter la
    moindre empreinte — et sans jamais se tromper.
    """

    def local_passages(self, audio: Path) -> list[Span]:
        ...


@runtime_checkable
class VoiceprintExtractor(Protocol):
    """Produit la signature vocale d'un extrait."""

    def extract_spans(self, audio: Path, intervalles: list[Span]) -> list[Voiceprint]:
        ...


@runtime_checkable
class VoiceBank(Protocol):
    """Mémoire des voix connues, d'une réunion à l'autre."""

    def people(self) -> list[Person]:
        ...

    def record(self, name: str, voiceprint: Voiceprint) -> Person:
        """Range l'empreinte et rend la personne, enrichie."""
        ...


@runtime_checkable
class Writer(Protocol):
    """Rédige le compte rendu à partir de la transcription attribuée."""

    def write_up(self, transcription: str) -> str:
        ...


@runtime_checkable
class Sender(Protocol):
    """Envoie le compte rendu."""

    def send(self, recipient: str, subject: str, corps: str, pieces: list[Path]) -> None:
        ...


@runtime_checkable
class MeetingStore(Protocol):
    """Garde une réunion traitée, et sait la relire.

    C'est ce qui manquait à la chaîne : l'écriture n'existait que dans la
    commande en ligne, donc une réunion terminée depuis la fenêtre ne laissait
    rien — ni dans la liste des réunions, ni de quoi nommer une voix après coup.
    """

    def record(self, meeting: StoredMeeting) -> Path:
        """Écrit le fichier maître et rend son chemin."""
        ...

    def read(self, identifier: str) -> StoredMeeting:
        """Relit une réunion déjà traitée, pour la nommer ou la reprendre.

        Déclaré ici parce que « nommer » en a besoin : sans lui, le cas d'usage
        se typait sur l'adaptateur concret, et la dépendance repartait à
        l'envers sans que rien ne le dise.
        """
        ...


@runtime_checkable
class Notifier(Protocol):
    """Prévient l'utilisateur pendant que la chaîne tourne, sans terminal ouvert."""

    def notify(self, title: str, message: str) -> None:
        ...


@runtime_checkable
class StateJournal(Protocol):
    """Publie l'avancement, pour que l'interface sache où en est la chaîne."""

    def publish(self, phase: str, message: str = "") -> None:
        ...
