"""Le vocabulaire d'une réunion.

Rien ici ne connaît whisper, sherpa, ffmpeg ni Outlook : ce sont des objets de
domaine, en dataclasses de la bibliothèque standard. C'est ce qui permet de
tester les règles métier — attribution des noms, reconnaissance des voix — sans
audio, sans modèle et sans réseau.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class MentionKind(StrEnum):
    """Qui la mention désigne, relativement à celui qui la prononce.

    Ici plutôt que dans `noms`, parce qu'un profil de langue décrit ses motifs
    avec ces valeurs : les laisser dans `noms` ferait tourner en rond les deux
    imports.
    """

    AUTO_PRESENTATION = "auto_presentation"   # le locuteur courant
    INTERPELLATION = "interpellation"         # le locuteur suivant
    RENVOI = "renvoi"                         # le locuteur précédent

class Phase(StrEnum):
    """États traversés par une réunion, de l'enregistrement à l'envoi."""

    REST = "repos"
    RECORDING = "enregistrement"
    PAUSE = "pause"
    FINALISATION = "finalisation"
    TRANSCRIPTION = "transcription"
    LOCUTEURS = "locuteurs"
    REDACTION = "redaction"
    ENVOI = "envoi"
    TERMINE = "termine"
    INTERROMPU = "interrompu"
    ECHEC = "echec"

    @property
    def in_progress(self) -> bool:
        return self in {
            Phase.RECORDING, Phase.FINALISATION, Phase.TRANSCRIPTION,
            Phase.LOCUTEURS, Phase.REDACTION, Phase.ENVOI,
        }

class Source(StrEnum):
    """D'où vient le son d'une réplique.

    En visio, le micro et l'audio système arrivent sur deux canaux distincts :
    c'est une certitude matérielle, pas une déduction acoustique. On la garde,
    parce qu'elle est plus fiable que n'importe quelle empreinte vocale.
    """

    MIC = "micro"          # la personne qui tient le Mac
    SYSTEM = "systeme"      # les participants distants
    INCONNUE = "inconnue"    # présentiel : une seule source pour tout le monde

@dataclass(frozen=True, slots=True)
class Span:
    start: float   # secondes depuis le début de l'enregistrement
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"intervalle inversé : {self.start} → {self.end}")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlap(self, autre: Span) -> float:
        """Durée commune aux deux intervalles, 0 s'ils sont disjoints."""
        return max(0.0, min(self.end, autre.end) - max(self.start, autre.start))

@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """Un segment où une même voix parle, tel que le rend la diarisation."""

    span: Span
    voice: str          # identifiant acoustique, pas un nom : « v1 », « v2 »…
    source: Source = Source.INCONNUE

@dataclass(slots=True)
class Utterance:
    """Une phrase transcrite, éventuellement rattachée à une voix.

    L'horodatage est conservé jusqu'au compte rendu : c'est ce qui permet de
    revenir à l'audio et de vérifier une citation. Rien ne doit se perdre entre
    la transcription et le document final.
    """

    span: Span
    text: str
    voice: str | None = None
    source: Source = Source.INCONNUE

@dataclass(frozen=True, slots=True)
class Voiceprint:
    """Signature vocale d'une personne, telle que la produit le modèle.

    Le vecteur est stocké normalisé : la comparaison se réduit alors à un
    produit scalaire, et deux enregistrements de volumes différents ne sont pas
    tenus pour deux personnes différentes.
    """

    vector: tuple[float, ...]
    source_duration: float = 0.0
    origine: str = ""

    def __post_init__(self) -> None:
        if not self.vector:
            raise ValueError("empreinte vide")

@dataclass(slots=True)
class Person:
    """Une personne connue de la banque de voix."""

    name: str
    voiceprints: list[Voiceprint] = field(default_factory=list)
    vu_le: datetime | None = None
    meetings: int = 0

@dataclass(slots=True)
class Meeting:
    """L'objet central : ce qui a été enregistré et ce qu'on en sait."""

    identifier: str
    title: str
    start: datetime
    audio: Path
    duration: float = 0.0
    phase: Phase = Phase.REST
    utterances: list[Utterance] = field(default_factory=list)
    turns: list[SpeakerTurn] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    personnes_en_salle: int | None = None

    def nom_de(self, voice: str | None) -> str:
        if voice is None:
            return "Indéterminé"
        return self.names.get(voice, voice)

    @property
    def speaking_time(self) -> dict[str, float]:
        """Secondes parlées par voix, silences exclus."""
        cumul: dict[str, float] = {}
        for turn in self.turns:
            cumul[turn.voice] = cumul.get(turn.voice, 0.0) + turn.span.duration
        return cumul

    def coverage(self) -> float:
        """Part de l'audio effectivement couverte par du texte transcrit.

        Un écart important révèle que whisper a décroché ou bouclé sur un
        passage. Le compte rendu doit le signaler plutôt que de laisser croire
        à une transcription complète.
        """
        if self.duration <= 0:
            return 0.0
        parlee = sum(r.span.duration for r in self.utterances)
        return min(1.0, parlee / self.duration)
