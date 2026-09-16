"""Processing a recorded meeting: from audio to minutes.

The order is not arbitrary. Everything expensive is written to disk before the
one step that leaves the machine, writing the minutes, because a writer
timeout used to lose a whole meeting's transcript and attribution.
"""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain import names as names_domain
from greffier.domain import profiles
from greffier.domain import voiceprints as voice_domain
from greffier.domain.attribution import voice_of
from greffier.domain.boilerplate import (
    collapse_loops,
    is_an_annotation,
    is_boilerplate,
)
from greffier.domain.her_voice import voices_of
from greffier.domain.language import LanguageProfile
from greffier.domain.meeting import StoredMeeting
from greffier.domain.minutes import title as title_of_the_minutes
from greffier.domain.models import (
    Phase,
    Span,
    SpeakerTurn,
    Utterance,
    Voiceprint,
)
from greffier.domain.profiles.neutral import NEUTRAL
from greffier.ports import outbound

SILENT_THRESHOLD_DB = -70.0

LOW_COVERAGE = 0.80
MINIMUM_WORDS = 20

#: Under this share of the speaking time, a voice that still passed the ten
#: second floor is more likely a remnant of somebody else than an attendee.
#: Measured on the meeting of 2026-09-10: six people, and three such voices
#: (37 s, 25 s and 16 s out of 3 878) that were pieces of the others.
THIN_VOICE_SHARE = 0.05

SILENT_LOOP_MARK = "· boucle système muette, à préciser"

SINGLE_TAKE_NOTE = (
    "Une seule prise de son pour toute la salle : aucun canal ne désigne qui "
    "parle, les noms viennent des voix seules. Relis-les si deux voix se ressemblent."
)

MATERIAL_TO_RECOGNISE = 6.0
"""Seconds of speech required before the voice bank may name a voice.

Measured on the meeting of 2026-09-10: the bank put "Sophie" on a voice holding
**3.1 seconds**, and Sophie was not in the room. It also named the nine
fragments of one Lise, each between 2.5 and 8.1 seconds. A few seconds of
speech resemble too many people, and a wrong label in minutes is worse than an
unnamed voice, because it is believed.

Six seconds, twice the calibration threshold below which an excerpt carries the
noise of the room more than the timbre. The same floor already guards the live
thread.
"""


class ChainStopped(Exception):
    """Deliberate stop of the chain, with a reason fit to show."""

    def __init__(self, phase: Phase, because: str) -> None:
        super().__init__(because)
        self.phase = phase
        self.because = because

@dataclass
class Outcome:
    audio: Path
    utterances: list[Utterance] = field(default_factory=list)
    turns: list[SpeakerTurn] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    propositions: dict[str, str] = field(default_factory=dict)
    minutes: str = ""
    sent: bool = False
    master_file: Path | None = None
    transcript_written: Path | None = None
    minutes_written: Path | None = None
    warnings: list[str] = field(default_factory=list)
    hardware_events: list[str] = field(default_factory=list)
    profile: LanguageProfile = NEUTRAL
    started_at: datetime | None = None
    ended_at: datetime | None = None
    subject: str = ""
    one_take: bool = False
    """One sound take for the whole room: a mono file, or a system loop that stayed silent."""

    @property
    def words(self) -> int:
        """The word count, counted the way the language separates them."""
        return sum(self.profile.splitting.count_them(r.text) for r in self.utterances)

    def name_of(self, voice: str | None) -> str:
        from greffier.domain.meeting import named_or_unknown

        return named_or_unknown(voice, self.names, self.speaking_time())

    def speaking_time(self) -> dict[str, float]:
        """Seconds spoken per voice, most talkative first."""
        cumulated: dict[str, float] = {}
        for turn in self.turns:
            cumulated[turn.voice] = cumulated.get(turn.voice, 0.0) + turn.span.duration
        return dict(sorted(cumulated.items(), key=lambda x: -x[1]))

    @property
    def duration(self) -> float:
        """Time the meeting covers, from the last turn."""
        return self.turns[-1].span.end if self.turns else 0.0

    @property
    def coverage(self) -> float:
        """Share of the audio that actually carries text."""
        if self.duration <= 0:
            return 0.0
        return min(1.0, sum(r.span.duration for r in self.utterances) / self.duration)

    def gaps(self, minimum: float = 5.0) -> list[Span]:
        """Passages of at least `minimum` seconds without a single utterance."""
        if not self.utterances:
            return [Span(0.0, self.duration)] if self.duration > minimum else []
        missing_ones: list[Span] = []
        previous = 0.0
        for utterance in sorted(self.utterances, key=lambda r: r.span.start):
            if utterance.span.start - previous >= minimum:
                missing_ones.append(Span(previous, utterance.span.start))
            previous = max(previous, utterance.span.end)
        if self.duration - previous >= minimum:
            missing_ones.append(Span(previous, self.duration))
        return missing_ones

    def significant_voices(self, minimum: float = 10.0) -> dict[str, float]:
        """Voices that spoke enough to be an attendee.

        Segmentation always leaves a trail of one-second fragments. Counting them as
        attendees would announce 22 people in a meeting of five.
        """
        return {v: d for v, d in self.speaking_time().items() if d >= minimum}

@dataclass
class Chain:
    """Wires the ports together. What is plugged where is decided elsewhere."""

    audio_recorder: outbound.AudioRecorder
    transcriber: outbound.Transcriber
    diariser: outbound.Diariser
    extractor: outbound.VoiceprintExtractor | None = None
    bank: outbound.VoiceBank | None = None
    writer: outbound.Writer | None = None
    sender: outbound.Sender | None = None
    log: outbound.StateJournal | None = None
    notificateur: outbound.Notifier | None = None
    store: outbound.MeetingStore | None = None
    memory: outbound.Memory | None = None
    transcripts_folder: Path | None = None
    minutes_folder: Path | None = None

    language: str = "fr"
    prompt_seed: str = ""
    context_header: str = ""
    instructions: Callable[[str], list[str]] | None = None
    named_live: Callable[[str], list[names_domain.NamedSpan]] | None = None
    people: int | None = None
    not_first_names: frozenset[str] = frozenset()
    recipient: str = ""
    disclosure: str = "rien"
    hardware_events: list[str] = field(default_factory=list)
    documents_supplied: list[str] = field(default_factory=list)
    expected_people: tuple[str, ...] = field(default=())
    her_name: str = ""
    her_turns_of: Callable[[str], tuple[tuple[float, float], ...]] | None = None
    preparation_taken: Callable[[str], None] | None = None
    _preparation_taken: bool = field(default=False, repr=False)

    def _phase(self, phase: Phase, message: str = "") -> None:
        if self.log:
            self.log.publish(phase.value, message)

    def _notify_user(self, title: str, message: str) -> None:
        if self.notificateur:
            self.notificateur.notify(title, message)

    def _check_audio(self, audio: Path, outcome: Outcome) -> None:
        """Refuses to transcribe a silent recording."""
        levels = self.audio_recorder.levels(audio)
        if not levels:
            return
        if all(level < SILENT_THRESHOLD_DB for level in levels):
            raise ChainStopped(
                Phase.FAILURE,
                "Enregistrement muet sur tous les canaux. "
                "Vérifie l'autorisation micro et le périphérique d'entrée.",
            )
        if len(levels) == 1:
            outcome.one_take = True
        elif levels[0] < SILENT_THRESHOLD_DB:
            outcome.warnings.append(
                "Ton micro est resté muet : seuls les autres participants sont transcrits."
            )
        elif max(levels[1:]) < SILENT_THRESHOLD_DB:
            outcome.warnings.append(SILENT_LOOP_MARK)

    def _say_what_the_channels_meant(self, outcome: Outcome) -> None:
        """Says what the silence of the system loop meant.

        Several voices through the microphone alone is a room: the take was
        single, and the reader is told so. One voice is a video call that may
        have lost everybody else.
        """
        if SILENT_LOOP_MARK in outcome.warnings:
            outcome.warnings.remove(SILENT_LOOP_MARK)
            if len(outcome.significant_voices()) > 1:
                outcome.one_take = True
            else:
                outcome.warnings.append(
                    "Aucun son système capté et une seule voix entendue : si la réunion "
                    "était en visio, les autres participants n'ont pas été enregistrés."
                )
        if outcome.one_take and len(outcome.significant_voices()) > 1:
            outcome.warnings.append(SINGLE_TAKE_NOTE)

    def _warn_about_coverage(self, outcome: Outcome) -> None:
        """Tells the user what the transcription lost."""
        from greffier.application.render import SIGNIFICANT_GAP, SUSPECT_COVERAGE

        coverage = outcome.coverage
        if coverage <= 0:
            return
        gaps = [t for t in outcome.gaps(SIGNIFICANT_GAP) if t.duration >= SIGNIFICANT_GAP]
        lost = sum(t.duration for t in gaps)
        if coverage < SUSPECT_COVERAGE:
            outcome.warnings.append(
                f"Couverture de {coverage * 100:.0f} % seulement : le modèle a "
                "probablement décroché sur une partie de la réunion. Le compte rendu "
                "en est averti, mais réécoute les passages qui te paraissent absents."
            )
        elif coverage < LOW_COVERAGE:
            outcome.warnings.append(
                f"Couverture de {coverage * 100:.0f} % : "
                f"{lost / 60:.0f} min sans aucun texte. Des silences peuvent "
                "l'expliquer, mais vérifie qu'il ne manque rien d'important."
            )
        elif gaps:
            outcome.warnings.append(
                f"{len(gaps)} passage(s) sans texte, {lost / 60:.0f} min au total. "
                "Un silence, ou du texte perdu : le compte rendu ne tranche pas."
            )

    def _warn_about_attendees(self, outcome: Outcome) -> None:
        """Says when the announced count contradicts what the audio holds.

        With no count announced, says when the count heard looks too high: a
        voice that carries almost none of the speaking time is more likely a
        piece of somebody else, and giving the count is what groups it back.
        """
        if self.people is None:
            self._suggest_the_count(outcome)
            return
        heard = len(outcome.significant_voices())
        if heard == 0 or heard == self.people:
            return
        outcome.warnings.append(
            f"{self.people} participants sont annoncés dans la configuration, "
            f"mais {heard} voix distinctes ont été entendues. Le nombre "
            "annoncé l'emporte, donc des personnes ont pu être confondues. "
            "Laisse « participants » vide pour que le nombre soit déduit."
        )

    def _suggest_the_count(self, outcome: Outcome) -> None:
        significant = outcome.significant_voices()
        total = sum(significant.values())
        thin = [v for v, seconds in significant.items() if seconds < THIN_VOICE_SHARE * total]
        if len(significant) < 3 or not thin:
            return
        outcome.warnings.append(
            f"{len(significant)} voix entendues, dont {len(thin)} qui parlent moins de "
            f"{THIN_VOICE_SHARE:.0%} du temps : peut-être des restes d'une autre voix. "
            "Si tu connais le nombre de participants, renseigne « participants » puis "
            "relance « Traiter » : les voix seront regroupées à ce nombre."
        )

    def _identify_voices(self, audio: Path, turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
        """Stitches back the voices the segmenter over-split.

        298 groups for three people around a table, measured on a real 92-minute
        meeting. Without this the minutes invent attendees.
        """
        if self.extractor is None:
            return turns
        per_voice: dict[str, list[Span]] = {}
        for turn in turns:
            per_voice.setdefault(turn.voice, []).append(turn.span)
        voiceprints = self._voiceprints_per_voice(audio, per_voice)
        membership = voice_domain.stitch(voiceprints)
        return [
            SpeakerTurn(t.span, membership.get(t.voice, t.voice), t.source) for t in turns
        ]

    def _voiceprints_per_voice(
        self, audio: Path, per_voice: dict[str, list[Span]]
    ) -> dict[str, list[Voiceprint]]:
        """The voiceprints of each voice, reading the audio only once."""
        from greffier.application.render import voiceprints_per_voice

        if self.extractor is None:
            return {}
        return voiceprints_per_voice(self.extractor, audio, per_voice)

    def _her_voices(self, turns: list[SpeakerTurn], identifier: str) -> set[str]:
        """The voices that are the assistant answering, not somebody in the room."""
        if self.her_turns_of is None or not self.her_name:
            return set()
        return voices_of(turns, self.her_turns_of(identifier))

    def _recognise(self, audio: Path, turns: list[SpeakerTurn]) -> dict[str, str]:
        """Names from the voice bank, for people already known."""
        if self.extractor is None or self.bank is None:
            return {}
        known = self.bank.people()
        if self.expected_people:
            expected = {name.casefold() for name in self.expected_people}
            known = [person for person in known if person.name.casefold() in expected]
        if not known:
            return {}
        found: dict[str, str] = {}
        per_voice: dict[str, list[Span]] = {}
        for turn in turns:
            per_voice.setdefault(turn.voice, []).append(turn.span)
        hers = self._her_voices(turns, audio.stem)
        for voice, the_spans in per_voice.items():
            if voice in hers:
                continue
            if sum(i.duration for i in the_spans) < MATERIAL_TO_RECOGNISE:
                continue
            excerpts = self.extractor.extract_spans(audio, the_spans)
            if not excerpts:
                continue
            match = voice_domain.recognise(voice_domain.aggregate(excerpts), known)
            if match and match.sure:
                found[voice] = match.name
        return found

    def _attribute_names(
        self,
        utterances: list[Utterance],
        turns: list[SpeakerTurn],
        from_bank: dict[str, str],
        outcome: Outcome,
    ) -> None:
        """Crosses the spoken names with the recognised voices.

        Both at once is a certainty. Either one alone stays a suggestion: better to ask
        than to write an invented name into minutes.
        """
        mentions = names_domain.spot_mentions(
            utterances, outcome.profile, self.not_first_names
        )
        attribution = names_domain.attribute(mentions, turns)

        hers = self._her_voices(turns, outcome.audio.stem)
        for voice in hers:
            outcome.names[voice] = self.her_name

        for voice, name in from_bank.items():
            if voice in hers:
                continue
            outcome.names[voice] = name

        for voice, found in attribution.certainties.items():
            if voice in hers:
                continue
            known_one = from_bank.get(voice)
            if known_one and known_one.lower() != found.name.lower():
                outcome.warnings.append(
                    f"La voix {voice} est reconnue comme {known_one} mais nommée {found.name} "
                    "pendant la réunion."
                )
                continue
            outcome.names[voice] = found.name

        for proposition in attribution.propositions:
            if proposition.voice in hers:
                continue
            if proposition.voice not in outcome.names:
                outcome.propositions[proposition.voice] = proposition.name

        self._names_given_live(turns, outcome)

    def _names_given_live(self, turns: list[SpeakerTurn], outcome: Outcome) -> None:
        """Fills in the names a human gave while the meeting ran.

        It fills silence and never overwrites: the live cut has its own mistakes
        measured on a real meeting, one of its voices carried two people, and
        carrying a name across a wrong cut takes one person's words and gives
        them to another. A disagreement is reported instead, for the writer to
        weigh.
        """
        if self.named_live is None:
            return
        named: list[names_domain.NamedSpan] = []
        with contextlib.suppress(Exception):
            named = self.named_live(outcome.audio.stem)
        for voice, name in names_domain.from_live(named, turns).items():
            other = outcome.names.get(voice)
            if other is None:
                outcome.names[voice] = name
                outcome.propositions.pop(voice, None)
            elif other.casefold() != name.casefold():
                outcome.warnings.append(
                    f"La voix {voice} est reconnue comme {other}, mais elle a "
                    f"été nommée {name} pendant la réunion. C'est {other} qui "
                    "a été retenu."
                )

    def _attach_voices(self, utterances: list[Utterance], turns: list[SpeakerTurn]) -> None:
        """Gives each utterance the voice that clearly holds it, else none."""
        for utterance in utterances:
            utterance.voice = voice_of(utterance.span, turns)

    def _join_namesakes(self, outcome: Outcome) -> None:
        """Folds onto one voice those that carry the same name.

        After attribution, not before: attribution is what gives the names, and here it
        is the name that says two voices are one person.
        """
        weight = {
            voice: sum(
                t.span.end - t.span.start
                for t in outcome.turns if t.voice == voice
            )
            for voice in set(outcome.names)
        }
        membership = names_domain.join_namesakes(outcome.names, weight)
        replies = {v: c for v, c in membership.items() if v != c}
        if not replies:
            return
        outcome.turns = [
            SpeakerTurn(
                t.span, membership.get(t.voice, t.voice), t.source
            )
            for t in outcome.turns
        ]
        for utterance in outcome.utterances:
            if utterance.voice is not None:
                utterance.voice = membership.get(utterance.voice, utterance.voice)
        for voice in replies:
            outcome.names.pop(voice, None)
            outcome.propositions.pop(voice, None)

    def run_chain(
        self,
        audio: Path,
        send: bool = True,
        hardware_events: list[str] | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> Outcome:
        self.hardware_events = list(hardware_events or [])
        outcome = Outcome(
            audio=audio,
            hardware_events=self.hardware_events,
            started_at=started_at,
            ended_at=ended_at,
        )

        self._phase(Phase.TRANSCRIPTION, "Vérification de l'enregistrement…")
        self._check_audio(audio, outcome)

        self._phase(Phase.TRANSCRIPTION, "Transcription…")
        with tempfile.TemporaryDirectory() as folder:
            prepare = self.audio_recorder.prepare_transcript(
                audio, Path(folder) / f"{audio.stem}-niveau.wav"
            )
            brutes = self.transcriber.transcribe(
                prepare, self.language, self.prompt_seed
            )
        profile = profiles.pour(self.language)
        outcome.profile = profile
        outcome.utterances = collapse_loops([
            r for r in brutes
            if not is_boilerplate(r.text, profile) and not is_an_annotation(r.text)
        ])
        if outcome.words < MINIMUM_WORDS:
            raise ChainStopped(
                Phase.FAILURE,
                f"Transcription quasi vide ({outcome.words} mots) : "
                "aucun compte rendu n'a été rédigé.",
            )

        self._phase(Phase.SPEAKERS, "Identification des locuteurs…")
        turns = self.diariser.segment(audio, self.people)
        turns = self._identify_voices(audio, turns)
        outcome.turns = turns
        self._attach_voices(outcome.utterances, turns)
        self._attribute_names(outcome.utterances, turns, self._recognise(audio, turns), outcome)
        self._join_namesakes(outcome)
        self._say_what_the_channels_meant(outcome)
        self._warn_about_coverage(outcome)
        self._warn_about_attendees(outcome)

        self._keep(audio, outcome)

        if self.writer is None:
            self._phase(Phase.DONE, "Transcription prête, aucun rédacteur configuré.")
            return outcome

        self._phase(Phase.WRITING, f"{outcome.words} mots transcrits. Rédaction…")
        from greffier.application.render import (
            context_header,
            disclosure_header,
            hardware_header,
            reliability_header,
            render_transcript,
            take_header,
        )

        duration = outcome.turns[-1].span.end if outcome.turns else 0.0
        heard = [
            v for v in outcome.significant_voices() if v
        ] + [v for v in outcome.names if v not in outcome.significant_voices()]
        header = (
            self._instructions_of(audio.stem)
            + context_header(audio.stem, duration,
                            names=[outcome.names[v] for v in heard if v in outcome.names],
                            voices_heard=len(heard),
                            started_at=outcome.started_at,
                            ended_at=outcome.ended_at)
            + take_header(outcome.one_take)
            + hardware_header(self.hardware_events)
            + reliability_header(outcome)
            + disclosure_header(self.disclosure)
            + self.context_header
        )
        outcome.minutes = self.writer.write_up(
            render_transcript(outcome, header)
        )
        written_title = title_of_the_minutes(outcome.minutes, "")
        if written_title:
            outcome.subject = (
                written_title.split(":", 1)[-1].strip() if ":" in written_title else written_title
            )

        self._keep(audio, outcome)

        if send and self.sender and self.recipient:
            self._phase(Phase.SENDING, "Envoi du compte rendu…")
            try:
                self._send(audio, outcome)
            except Exception as trouble:  # noqa: BLE001
                outcome.warnings.append(
                    f"Compte rendu NON envoyé : {trouble} "
                    "Le compte rendu est gardé ; « greffier envoyer » réessaie."
                )
            else:
                outcome.sent = True
        elif send:
            lack = ("aucun destinataire n'est configuré" if not self.recipient
                      else "aucun moyen d'envoi n'est configuré")
            outcome.warnings.append(
                f"Compte rendu NON envoyé : {lack}. "
                "« greffier envoyer » pour l'expédier, ou renseigne "
                "compte_rendu.destinataire dans la configuration."
            )

        self._phase(
            Phase.DONE,
            "Compte rendu envoyé." if outcome.sent else "Compte rendu prêt, non envoyé.",
        )
        self._notify_user("Greffier", "Compte rendu prêt.")
        return outcome

    def _instructions_of(self, identifier: str) -> str:
        """What was asked of the tool during this meeting, for the writer.

        Never raises: minutes are worth more than a header, and a conversation
        that cannot be read must not cost the meeting.
        """
        from greffier.application.render import instructions_header

        if self.instructions is None:
            return ""
        with contextlib.suppress(Exception):
            return instructions_header(self.instructions(identifier))
        return ""

    def _keep(self, audio: Path, outcome: Outcome) -> None:
        """Writes the master file, the transcript and the minutes."""
        from greffier.application.render import render_transcript

        duration = outcome.turns[-1].span.end if outcome.turns else 0.0
        if self.store is not None:
            with contextlib.suppress(Exception):
                kept = self.store.read(outcome.audio.stem).subject
                if kept:
                    outcome.subject = kept
            outcome.master_file = self.store.record(
                _as_stored_meeting(outcome, duration))
        if self.transcripts_folder is None:
            return
        transcription = self.transcripts_folder / f"{audio.stem}.txt"
        transcription.parent.mkdir(parents=True, exist_ok=True)
        transcription.write_text(render_transcript(outcome), encoding="utf-8")
        outcome.transcript_written = transcription
        if outcome.minutes and self.minutes_folder is not None:
            minutes = self.minutes_folder / f"{audio.stem}.md"
            minutes.parent.mkdir(parents=True, exist_ok=True)
            minutes.write_text(outcome.minutes, encoding="utf-8")
            outcome.minutes_written = minutes
        self._leave_a_trace(audio, outcome)
        if self.preparation_taken is not None and not self._preparation_taken:
            # Once, and after the meeting is on disk. `_keep` runs twice -- once
            # before the minutes are written and once after -- and a processing
            # that fails halfway must burn no preparation at all.
            self._preparation_taken = True
            with contextlib.suppress(Exception):
                self.preparation_taken(audio.stem)

    @staticmethod
    def _the_day(outcome: Outcome, audio: Path) -> str:
        """When the meeting was held, or failing that when it was recorded.

        A recording processed after the fact carries no start: the chain is
        being handed a file, not running a meeting. The file's own date is then
        closer to the truth than nothing at all.
        """
        if outcome.started_at is not None:
            return outcome.started_at.date().isoformat()
        with contextlib.suppress(OSError):
            return datetime.fromtimestamp(audio.stat().st_mtime).date().isoformat()
        return ""

    def _leave_a_trace(self, audio: Path, outcome: Outcome) -> None:
        """Files what this meeting leaves for the next ones.

        Read from the minutes rather than asked for a second time: the model has
        already sorted that material once, and asking again would cost a call
        and answer the same question differently.

        Never raises. A meeting whose minutes are written has done its work;
        failing it over a line of memory would be absurd.
        """
        if self.memory is None or not outcome.minutes:
            return
        from greffier.domain.memory import Trace, what_the_minutes_left

        with contextlib.suppress(Exception):
            decisions, open_ones = what_the_minutes_left(outcome.minutes)
            self.memory.remember(Trace(
                identifier=audio.stem,
                title=title_of_the_minutes(outcome.minutes, audio.stem),
                held_on=self._the_day(outcome, audio),
                people=tuple(dict.fromkeys(outcome.names.values())),
                decisions=decisions,
                open_points=open_ones,
                documents=tuple(self.documents_supplied),
            ))

    def _send(self, audio: Path, outcome: Outcome) -> None:
        """Sends the minutes, with no attachment."""
        assert self.sender is not None
        self.sender.send(
            self.recipient,
            title_of_the_minutes(
                outcome.minutes, f"Compte rendu de réunion : {audio.stem}"
            ),
            outcome.minutes,
            [],
        )

def _as_stored_meeting(outcome: Outcome, duration: float) -> StoredMeeting:
    """The master file, from what the chain produced."""
    return StoredMeeting(
        identifier=outcome.audio.stem,
        audio=outcome.audio,
        processed_at=datetime.now(UTC),
        duration=duration,
        utterances=outcome.utterances,
        turns=outcome.turns,
        names=dict(outcome.names),
        propositions=dict(outcome.propositions),
        warnings=list(outcome.warnings),
        hardware_events=list(outcome.hardware_events),
        subject=outcome.subject,
        started_at=outcome.started_at,
        ended_at=outcome.ended_at,
        one_take=outcome.one_take,
    )
