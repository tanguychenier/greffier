"""A processed meeting, as it is kept."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from greffier.domain.models import Span, SpeakerTurn, Utterance

HORODATAGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:_(\d{2})h(\d{2}))?")

def held_on(identifier: str) -> tuple[int, int, int, int, int] | None:
    """When the meeting was held, from its identifier."""
    trouve = HORODATAGE.match(identifier)
    if trouve is None:
        return None
    annee, mois, jour, heure, minute = trouve.groups()
    return (int(annee), int(mois), int(jour), int(heure or 0), int(minute or 0))

@dataclass
class StoredMeeting:
    """A processed meeting, as it sits on disk."""

    identifier: str
    audio: Path
    traitee_le: datetime
    duration: float
    utterances: list[Utterance]
    turns: list[SpeakerTurn]
    names: dict[str, str]
    propositions: dict[str, str]
    warnings: list[str]
    hardware_events: list[str] = field(default_factory=list)
    subject: str = ""
    commencee_le: datetime | None = None
    terminee_le: datetime | None = None

    def attendees(self, minimum: float = 10.0) -> list[str]:
        """The voices that carried the meeting, most talkative first."""
        temps = self.speaking_time()
        return [
            voice for voice, duration in temps.items()
            if duration >= minimum or voice in self.names
        ]

    def voice_named(self, name: str) -> list[str]:
        """The voices already given that name, in this meeting."""
        replie = name.casefold()
        return [v for v, porte in self.names.items() if porte.casefold() == replie]

    def join_into(self, absorbee: str, gardee: str) -> int:
        """Pours every turn and utterance of one voice into another."""
        if absorbee == gardee:
            return 0
        deplaces = sum(1 for t in self.turns if t.voice == absorbee)
        self.turns = [
            replace(turn, voice=gardee) if turn.voice == absorbee else turn
            for turn in self.turns
        ]
        for utterance in self.utterances:
            if utterance.voice == absorbee:
                utterance.voice = gardee
        self.names.pop(absorbee, None)
        self.propositions.pop(absorbee, None)
        return deplaces

    @property
    def caption(self) -> str:
        """What names the meeting: the chosen subject, else the identifier."""
        return self.subject or self.identifier

    @property
    def coverage(self) -> float:
        """Share of the audio actually covered by text."""
        if self.duration <= 0:
            return 0.0
        return min(1.0, sum(r.span.duration for r in self.utterances) / self.duration)

    def gaps(self, minimum: float = 5.0) -> list[Span]:
        """Passages of at least `minimum` seconds without a single utterance."""
        if not self.utterances:
            return [Span(0.0, self.duration)] if self.duration > minimum else []
        manques: list[Span] = []
        ordonnees = sorted(self.utterances, key=lambda r: r.span.start)
        precedent = 0.0
        for utterance in ordonnees:
            if utterance.span.start - precedent >= minimum:
                manques.append(Span(precedent, utterance.span.start))
            precedent = max(precedent, utterance.span.end)
        if self.duration - precedent >= minimum:
            manques.append(Span(precedent, self.duration))
        return manques

    def nom_de(self, voice: str | None) -> str:
        if voice is None:
            return "Indéterminé"
        return self.names.get(voice, f"Personne {voice}")

    def spans_of(self, voice: str) -> list[Span]:
        return [t.span for t in self.turns if t.voice == voice]

    def speaking_time(self) -> dict[str, float]:
        cumul: dict[str, float] = {}
        for turn in self.turns:
            cumul[turn.voice] = cumul.get(turn.voice, 0.0) + turn.span.duration
        return dict(sorted(cumul.items(), key=lambda x: -x[1]))
