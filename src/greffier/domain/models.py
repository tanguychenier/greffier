"""The vocabulary of a meeting.

Every other module speaks in these terms. They carry no behaviour beyond what
can be derived from their own fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MentionKind(StrEnum):
    """Who the mention points at, relative to whoever speaks it."""

    AUTO_PRESENTATION = "auto_presentation"   # the current speaker
    ADDRESSING = "interpellation"         # the next speaker
    REFERRAL = "renvoi"                         # the previous speaker

class Phase(StrEnum):
    """The states a meeting goes through, from recording to sending."""

    REST = "repos"
    RECORDING = "enregistrement"
    PAUSE = "pause"
    FINALISING = "finalisation"
    TRANSCRIPTION = "transcription"
    SPEAKERS = "locuteurs"
    WRITING = "redaction"
    SENDING = "envoi"
    DONE = "termine"
    INTERRUPTED = "interrompu"
    FAILURE = "echec"

    @property
    def in_progress(self) -> bool:
        return self in {
            Phase.RECORDING, Phase.FINALISING, Phase.TRANSCRIPTION,
            Phase.SPEAKERS, Phase.WRITING, Phase.SENDING,
        }

class Source(StrEnum):
    """Where an utterance's sound comes from."""

    MIC = "micro"          # the person holding the Mac
    SYSTEM = "systeme"      # the remote attendees
    UNKNOWN = "inconnue"    # in a room: one source for everybody

@dataclass(frozen=True, slots=True)
class Span:
    start: float   # seconds since the start of the recording
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"intervalle inversé : {self.start} → {self.end}")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlap(self, other: Span) -> float:
        """Time common to both spans, 0 when they are disjoint."""
        return max(0.0, min(self.end, other.end) - max(self.start, other.start))

@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """A segment where one voice speaks, as diarisation returns it."""

    span: Span
    voice: str          # an acoustic identifier, not a name: « v1 », « v2 »…
    source: Source = Source.UNKNOWN

@dataclass(slots=True)
class Utterance:
    """A transcribed sentence, possibly attached to a voice."""

    span: Span
    text: str
    voice: str | None = None
    source: Source = Source.UNKNOWN
    confidence: float | None = None
    """How sure the model was of these words, between 0 and 1.

    None where the engine did not say, which is not the same as zero: a turn
    the tool cannot judge must not be shown as a turn it doubts.
    """

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
