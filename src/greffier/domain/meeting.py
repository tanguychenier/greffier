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
    found = HORODATAGE.match(identifier)
    if found is None:
        return None
    year, month, day, the_hour, minute = found.groups()
    return (int(year), int(month), int(day), int(the_hour or 0), int(minute or 0))

IDENTIFIABLE_SECONDS = 6.0

def named_or_unknown(
    voice: str | None,
    names: dict[str, str],
    speaking: dict[str, float],
    floor: float = IDENTIFIABLE_SECONDS,
) -> str:
    """What a voice is called, and « Indéterminé » when it cannot be anybody.

    Measured on four AMI meetings against their manual annotations, through the
    microphone in the middle of the table: above six seconds of speech the chain
    finds exactly one voice per person, four for four, none split and none
    confused. Below it, the scraps -- a « oui », a « hmm », a crossing of two
    people -- were each given a number of their own, and a meeting of four came
    out announcing eleven and twenty people.

    A voice somebody has named keeps its name whatever it holds: the human
    correction is the one thing nothing argues with.
    """
    if voice is None:
        return "Indéterminé"
    if voice in names:
        return names[voice]
    if speaking.get(voice, 0.0) < floor:
        return "Indéterminé"
    return f"Personne {voice}"

@dataclass(frozen=True, slots=True)
class Join:
    """What has to be kept in order to undo a join of two voices.

    The live thread has carried this since the day two people joined by mistake
    stayed one until the minutes. The after-meeting chain had the same gesture
    and no way back: naming two voices alike retagged every turn and dropped
    the absorbed name, and nothing said which turns had moved.
    """

    absorbed: str
    kept: str
    turns: tuple[int, ...]
    utterances: tuple[int, ...]
    name: str | None = None
    proposition: str | None = None


@dataclass
class StoredMeeting:
    """A processed meeting, as it sits on disk."""

    identifier: str
    audio: Path
    processed_at: datetime
    duration: float
    utterances: list[Utterance]
    turns: list[SpeakerTurn]
    names: dict[str, str]
    propositions: dict[str, str]
    warnings: list[str]
    hardware_events: list[str] = field(default_factory=list)
    subject: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    joins: list[Join] = field(default_factory=list)
    one_take: bool = False
    """One sound take for the whole room: no channel says who is speaking."""

    def attendees(self, minimum: float = 10.0) -> list[str]:
        """The voices that carried the meeting, most talkative first."""
        temps = self.speaking_time()
        return [
            voice for voice, duration in temps.items()
            if duration >= minimum or voice in self.names
        ]

    def voice_named(self, name: str) -> list[str]:
        """The voices already given that name, in this meeting."""
        folded = name.casefold()
        return [v for v, carries in self.names.items() if carries.casefold() == folded]

    def join_into(self, absorbed_one: str, kept_one: str) -> int:
        """Pours every turn and utterance of one voice into another.

        Records what it takes to undo it: which turns and which utterances
        moved, and what the absorbed voice was called.
        """
        if absorbed_one == kept_one:
            return 0
        ranks = tuple(i for i, t in enumerate(self.turns) if t.voice == absorbed_one)
        said_ones = tuple(
            i for i, u in enumerate(self.utterances) if u.voice == absorbed_one
        )
        self.joins.append(Join(
            absorbed=absorbed_one, kept=kept_one, turns=ranks, utterances=said_ones,
            name=self.names.get(absorbed_one),
            proposition=self.propositions.get(absorbed_one),
        ))
        self.turns = [
            replace(turn, voice=kept_one) if turn.voice == absorbed_one else turn
            for turn in self.turns
        ]
        for utterance in self.utterances:
            if utterance.voice == absorbed_one:
                utterance.voice = kept_one
        self.names.pop(absorbed_one, None)
        self.propositions.pop(absorbed_one, None)
        return len(ranks)

    def can_split(self, kept: str) -> bool:
        """True when this voice absorbed another one that can be taken back."""
        return any(f.kept == kept for f in self.joins)

    def split(self, kept: str) -> Join | None:
        """Undoes the last join that produced this voice.

        Gives the absorbed voice back its identifier, its turns, its utterances
        and the name it carried. Returns nothing when there is nothing to undo.
        """
        returned = next((f for f in reversed(self.joins) if f.kept == kept), None)
        if returned is None:
            return None
        for rang in returned.turns:
            if 0 <= rang < len(self.turns):
                self.turns[rang] = replace(
                    self.turns[rang], voice=returned.absorbed
                )
        for rang in returned.utterances:
            if 0 <= rang < len(self.utterances):
                self.utterances[rang].voice = returned.absorbed
        if returned.name:
            self.names[returned.absorbed] = returned.name
        if returned.proposition:
            self.propositions[returned.absorbed] = returned.proposition
        self.joins.remove(returned)
        return returned

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
        missing_ones: list[Span] = []
        ordered = sorted(self.utterances, key=lambda r: r.span.start)
        previous = 0.0
        for utterance in ordered:
            if utterance.span.start - previous >= minimum:
                missing_ones.append(Span(previous, utterance.span.start))
            previous = max(previous, utterance.span.end)
        if self.duration - previous >= minimum:
            missing_ones.append(Span(previous, self.duration))
        return missing_ones

    def name_of(self, voice: str | None) -> str:
        return named_or_unknown(voice, self.names, self.speaking_time())

    def spans_of(self, voice: str) -> list[Span]:
        return [t.span for t in self.turns if t.voice == voice]

    def speaking_time(self) -> dict[str, float]:
        cumulated: dict[str, float] = {}
        for turn in self.turns:
            cumulated[turn.voice] = cumulated.get(turn.voice, 0.0) + turn.span.duration
        return dict(sorted(cumulated.items(), key=lambda x: -x[1]))
