"""The vocabulary of a meeting.

Every other module speaks in these terms. They carry no behaviour beyond what
can be derived from their own fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class MentionKind(StrEnum):
    """Who the mention points at, relative to whoever speaks it."""

    AUTO_PRESENTATION = "auto_presentation"   # le locuteur courant
    INTERPELLATION = "interpellation"         # le locuteur suivant
    RENVOI = "renvoi"                         # le locuteur précédent

class Phase(StrEnum):
    """The states a meeting goes through, from recording to sending."""

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
    """Where an utterance's sound comes from."""

    MIC = "micro"          # la personne qui tient le Mac
    SYSTEM = "systeme"      # les participants distants
    UNKNOWN = "inconnue"    # présentiel : une seule source pour tout le monde

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
        """Time common to both spans, 0 when they are disjoint."""
        return max(0.0, min(self.end, autre.end) - max(self.start, autre.start))

@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """A segment where one voice speaks, as diarisation returns it."""

    span: Span
    voice: str          # identifiant acoustique, pas un nom : « v1 », « v2 »…
    source: Source = Source.UNKNOWN

@dataclass(slots=True)
class Utterance:
    """A transcribed sentence, possibly attached to a voice."""

    span: Span
    text: str
    voice: str | None = None
    source: Source = Source.UNKNOWN

@dataclass(frozen=True, slots=True)
class Voiceprint:
    """A person's vocal signature, as the model produces it."""

    vector: tuple[float, ...]
    source_duration: float = 0.0
    origin: str = ""

    def __post_init__(self) -> None:
        if not self.vector:
            raise ValueError("empreinte vide")

@dataclass(slots=True)
class Person:
    """Someone the voice bank knows."""

    name: str
    voiceprints: list[Voiceprint] = field(default_factory=list)
    seen_at: datetime | None = None
    meetings: int = 0

@dataclass(slots=True)
class Meeting:
    """The central object: what was recorded and what is known of it."""

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

    def name_of(self, voice: str | None) -> str:
        if voice is None:
            return "Indéterminé"
        return self.names.get(voice, voice)

    @property
    def speaking_time(self) -> dict[str, float]:
        """Seconds spoken per voice, silences excluded."""
        cumul: dict[str, float] = {}
        for turn in self.turns:
            cumul[turn.voice] = cumul.get(turn.voice, 0.0) + turn.span.duration
        return cumul

    def coverage(self) -> float:
        """Share of the audio actually covered by transcribed text."""
        if self.duration <= 0:
            return 0.0
        parlee = sum(r.span.duration for r in self.utterances)
        return min(1.0, parlee / self.duration)
