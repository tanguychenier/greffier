"""Giving a voice a name, after the meeting."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from greffier.domain import first_names
from greffier.domain import voiceprints as empreintes_domaine
from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span
from greffier.domain.voiceprints import aggregate
from greffier.ports import outbound

EXTRACT_LENGTH = 10.0
USEFUL_LENGTH = 3.0

@dataclass
class VoiceToName:
    """A voice of the meeting, as it is presented for naming."""

    voice: str
    duration: float
    part: float
    name: str | None = None          # déjà nommée
    proposition: str | None = None  # nom deviné, à confirmer
    extrait: Span | None = None

    @property
    def to_name(self) -> bool:
        return self.name is None

def voices_to_name(meeting: StoredMeeting, minimum: float = 10.0) -> list[VoiceToName]:
    """The meeting's voices, most talkative first."""
    temps = meeting.speaking_time()
    total = sum(d for d in temps.values() if d >= minimum) or 1.0
    outcome = []
    for voice, duration in temps.items():
        if duration < minimum and not (meeting.names.get(voice) or meeting.propositions.get(voice)):
            continue
        outcome.append(VoiceToName(
            voice=voice,
            duration=duration,
            part=duration / total,
            name=meeting.names.get(voice),
            proposition=meeting.propositions.get(voice),
            extrait=best_excerpt(meeting.spans_of(voice)),
        ))
    return outcome

def best_excerpt(intervalles: list[Span]) -> Span | None:
    """The most representative passage to play back."""
    utiles = [i for i in intervalles if i.duration >= USEFUL_LENGTH]
    if not utiles:
        utiles = intervalles
    if not utiles:
        return None
    longer = max(utiles, key=lambda i: i.duration)
    if longer.duration <= EXTRACT_LENGTH:
        return longer
    start = longer.start + min(1.0, (longer.duration - EXTRACT_LENGTH) / 2)
    return Span(start, start + EXTRACT_LENGTH)

def extract_audio(audio: Path, span: Span, destination: Path) -> Path:
    """Cuts an excerpt out, to listen to it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{span.start:.3f}", "-t", f"{span.duration:.3f}",
         "-i", str(audio), "-c:a", "pcm_s16le", str(destination)],
        check=True,
    )
    return destination

@dataclass
class Naming:
    """Ties a voice to a name, and puts the voiceprint into the bank."""

    store: outbound.MeetingStore
    bank: outbound.VoiceBank
    extractor: outbound.VoiceprintExtractor
    doute: str = ""

    def name_voice(self, identifier: str, voice: str, name: str) -> StoredMeeting:
        """Puts a name on a voice, and joins those that carry the same one."""
        refuse = first_names.refusal(name)
        if refuse:
            raise ValueError(refuse)
        name = first_names.normalise(name)
        meeting = self.store.read(identifier)
        intervalles = meeting.spans_of(voice)
        if not intervalles:
            raise KeyError(
                f"La voix « {voice} » n'existe pas dans cette réunion. "
                f"Voix connues : {', '.join(sorted(meeting.speaking_time()))}"
            )
        voiceprints = self.extractor.extract_spans(meeting.audio, intervalles)
        if not voiceprints:
            raise ValueError(
                f"La voix « {voice} » n'a aucun passage d'au moins {USEFUL_LENGTH:.0f} s : "
                "trop peu de matière pour une empreinte fiable."
            )
        aggregate_of = replace(aggregate(voiceprints), origin=identifier)
        self.doute = empreintes_domaine.doubtful_entry(
            aggregate_of, name, self.bank.people())
        self.bank.record(name, aggregate_of)

        meeting.names[voice] = name
        meeting.propositions.pop(voice, None)
        temps = meeting.speaking_time()
        homonymes = [v for v in meeting.voice_named(name) if v != voice]
        for other in homonymes:
            gardee, absorbee = (
                (voice, other) if temps.get(voice, 0.0) >= temps.get(other, 0.0)
                else (other, voice)
            )
            meeting.join_into(absorbee, gardee)
            meeting.names[gardee] = name
            voice = gardee
        self.store.record(meeting)
        return meeting

    def split(self, identifier: str, voice: str) -> StoredMeeting:
        """Undoes the last join that produced this voice, in the meeting.

        The gesture the live thread has and the after-meeting chain did not.
        Naming two voices alike joins them, which is what one wants when the
        tool split one person in two, and there was no way back when it was
        the other way round.

        The voiceprints of the two people stay in the bank under the name they
        were filed under: separating a meeting does not unlearn a voice. The
        bank has its own gestures for that, and « greffier connus » shows what
        looks doubtful.
        """
        meeting = self.store.read(identifier)
        if not meeting.can_split(voice):
            raise KeyError(
                f"La voix « {voice} » n'a absorbé aucune autre voix : "
                "il n'y a rien à séparer."
            )
        rendue = meeting.split(voice)
        assert rendue is not None
        self.store.record(meeting)
        return meeting

    def forget(self, identifier: str, voice: str) -> StoredMeeting:
        """Removes a voice's name, within the meeting."""
        meeting = self.store.read(identifier)
        if voice not in meeting.names and voice not in meeting.propositions:
            raise KeyError(f"La voix « {voice} » ne porte aucun nom.")
        meeting.names.pop(voice, None)
        meeting.propositions.pop(voice, None)
        self.store.record(meeting)
        return meeting

    def accepter_propositions(self, identifier: str) -> dict[str, str]:
        """Approves in one go every name guessed during the meeting."""
        meeting = self.store.read(identifier)
        acceptes = dict(meeting.propositions)
        for voice, name in acceptes.items():
            self.name_voice(identifier, voice, name)
        return acceptes
