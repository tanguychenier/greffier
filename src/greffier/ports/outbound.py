"""What the domain expects of the outside world.

Protocols rather than base classes: an adapter has nothing to inherit, it only
needs the right shape. Each port matches one thing that differs from system to
system or from tool to tool — which is exactly the list of what has to be
rewritten for Windows, or the day the transcription model changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Person, Span, SpeakerTurn, Utterance, Voiceprint


@runtime_checkable
class AudioRecorder(Protocol):
    """Captures the sound of the meeting.

    The only port whose implementation truly differs across the three systems:
    hearing your own voice is trivial, recording back what the speakers play is
    not.
    """

    def start_recording(self, destination: Path) -> int:
        """Starts recording in the background, returns the process identifier."""
        ...

    def stop_recording(self, processus: int) -> None:
        """Stops cleanly, leaving the audio file usable."""
        ...

    def try_it(self, peripherique: str, seconds: float = 1.5) -> float:
        """Level captured by an input, in decibels. -120 when it does not open.

        A mic can be plugged in, recognised, turned up, and still mute: USB headsets
        have a mute button on the cable.
        """
        ...

    def prepare_transcript(self, audio: Path, destination: Path) -> Path:
        """Brings the recording to the level transcription expects.

        A weak signal does not give a poor transcript, it gives an invented one. Each
        channel is levelled separately before mixing, or the voice 12 dB below the rest
        stays 12 dB below and is the one the model makes up.
        """
        ...

    def wire_up(self, chunks: list[Path], destination: Path) -> Path:
        """Stitches the chunks of a recording into a single file.

        A recording splits into chunks whenever the hardware changes mid-meeting, and
        the rest of the chain expects one continuous stream.
        """
        ...

    def levels(self, audio: Path) -> list[float]:
        """Mean level of each channel, in dB. -120 for a mute channel."""
        ...


@runtime_checkable
class Transcriber(Protocol):
    """Turns audio into timestamped utterances."""

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        ...


@runtime_checkable
class Diariser(Protocol):
    """Cuts the audio into speaker turns and groups the voices."""

    def segment(self, audio: Path, people: int | None) -> list[SpeakerTurn]:
        ...


@runtime_checkable
class ChannelReader(Protocol):
    """Says which passages of a recording came from the mic.

    The only port whose answer comes from no model: it is wiring, and it is never
    wrong.
    """

    def local_passages(self, audio: Path) -> list[Span]:
        ...


@runtime_checkable
class VoiceprintExtractor(Protocol):
    """Produces the vocal signature of an excerpt."""

    def extract_spans(self, audio: Path, intervalles: list[Span]) -> list[Voiceprint]:
        ...


@runtime_checkable
class VoiceBank(Protocol):
    """Memory of the known voices, from one meeting to the next."""

    def people(self) -> list[Person]:
        ...

    def record(self, name: str, voiceprint: Voiceprint) -> Person:
        """Files the voiceprint and returns the person, enriched."""
        ...


@runtime_checkable
class Writer(Protocol):
    """Writes the minutes from the attributed transcript."""

    def write_up(self, transcription: str) -> str:
        ...


@runtime_checkable
class Sender(Protocol):
    """Sends the minutes."""

    def send(self, recipient: str, subject: str, corps: str, pieces: list[Path]) -> None:
        ...


@runtime_checkable
class MeetingStore(Protocol):
    """Keeps a processed meeting, and knows how to read it back."""

    def record(self, meeting: StoredMeeting) -> Path:
        """Writes the master file and returns its path."""
        ...

    def read(self, identifier: str) -> StoredMeeting:
        """Reads back a processed meeting, to name it or resume it."""
        ...


@runtime_checkable
class Notifier(Protocol):
    """Tells the user while the chain runs, with no terminal open."""

    def notify(self, title: str, message: str) -> None:
        ...


@runtime_checkable
class StateJournal(Protocol):
    """Publishes progress, so the interface knows where the chain is."""

    def publish(self, phase: str, message: str = "") -> None:
        ...
