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

DUREE_EXTRAIT = 10.0
DUREE_UTILE = 3.0

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
    utiles = [i for i in intervalles if i.duration >= DUREE_UTILE]
    if not utiles:
        utiles = intervalles
    if not utiles:
        return None
    plus_long = max(utiles, key=lambda i: i.duration)
    if plus_long.duration <= DUREE_EXTRAIT:
        return plus_long
    start = plus_long.start + min(1.0, (plus_long.duration - DUREE_EXTRAIT) / 2)
    return Span(start, start + DUREE_EXTRAIT)

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
                f"La voix « {voice} » n'a aucun passage d'au moins {DUREE_UTILE:.0f} s : "
                "trop peu de matière pour une empreinte fiable."
            )
        aggregate_of = replace(aggregate(voiceprints), origine=identifier)
        self.doute = empreintes_domaine.doubtful_entry(
            aggregate_of, name, self.bank.people())
        self.bank.record(name, aggregate_of)

        meeting.names[voice] = name
        meeting.propositions.pop(voice, None)
        temps = meeting.speaking_time()
        homonymes = [v for v in meeting.voice_named(name) if v != voice]
        for autre in homonymes:
            gardee, absorbee = (
                (voice, autre) if temps.get(voice, 0.0) >= temps.get(autre, 0.0)
                else (autre, voice)
            )
            meeting.join_into(absorbee, gardee)
            meeting.names[gardee] = name
            voice = gardee
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
