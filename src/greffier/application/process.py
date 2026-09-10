"""Processing a recorded meeting: from audio to minutes.

The order is not arbitrary. Everything expensive is written to disk before the
one step that leaves the machine — writing the minutes — because a writer
timeout used to lose a whole meeting's transcript and attribution.
"""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain import names as noms_domaine
from greffier.domain import profiles
from greffier.domain import voiceprints as voix_domaine
from greffier.domain.attribution import voice_of
from greffier.domain.boilerplate import (
    collapse_loops,
    is_an_annotation,
    is_boilerplate,
)
from greffier.domain.language import LanguageProfile
from greffier.domain.meeting import StoredMeeting
from greffier.domain.minutes import title as titre_du_compte_rendu
from greffier.domain.models import (
    Phase,
    Span,
    SpeakerTurn,
    Utterance,
    Voiceprint,
)
from greffier.domain.profiles.neutral import NEUTRAL
from greffier.ports import outbound

SEUIL_MUET_DB = -70.0

COUVERTURE_BASSE = 0.80
MOTS_MINIMUM = 20

AVERTISSEMENT_SANS_BOUCLE = "· boucle système muette, à préciser"

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
    envoye: bool = False
    fichier_maitre: Path | None = None
    transcript_written: Path | None = None
    compte_rendu_ecrit: Path | None = None
    warnings: list[str] = field(default_factory=list)
    hardware_events: list[str] = field(default_factory=list)
    profil: LanguageProfile = NEUTRAL
    commencee_le: datetime | None = None
    terminee_le: datetime | None = None
    subject: str = ""

    @property
    def words(self) -> int:
        """The word count, counted the way the language separates them."""
        return sum(self.profil.decoupage.count_them(r.text) for r in self.utterances)

    def nom_de(self, voice: str | None) -> str:
        if voice is None:
            return "Indéterminé"
        return self.names.get(voice, f"Personne {voice}")

    def speaking_time(self) -> dict[str, float]:
        """Seconds spoken per voice, most talkative first."""
        cumul: dict[str, float] = {}
        for turn in self.turns:
            cumul[turn.voice] = cumul.get(turn.voice, 0.0) + turn.span.duration
        return dict(sorted(cumul.items(), key=lambda x: -x[1]))

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
        manques: list[Span] = []
        precedent = 0.0
        for utterance in sorted(self.utterances, key=lambda r: r.span.start):
            if utterance.span.start - precedent >= minimum:
                manques.append(Span(precedent, utterance.span.start))
            precedent = max(precedent, utterance.span.end)
        if self.duration - precedent >= minimum:
            manques.append(Span(precedent, self.duration))
        return manques

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
    dossier_transcriptions: Path | None = None
    dossier_comptes_rendus: Path | None = None

    language: str = "fr"
    prompt_seed: str = ""
    context_header: str = ""
    instructions: Callable[[str], list[str]] | None = None
    people: int | None = None
    not_first_names: frozenset[str] = frozenset()
    recipient: str = ""
    disclosure: str = "rien"
    hardware_events: list[str] = field(default_factory=list)

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
        if all(level < SEUIL_MUET_DB for level in levels):
            raise ChainStopped(
                Phase.ECHEC,
                "Enregistrement muet sur tous les canaux. "
                "Vérifie l'autorisation micro et le périphérique d'entrée.",
            )
        if len(levels) >= 2:
            if levels[0] < SEUIL_MUET_DB:
                outcome.warnings.append(
                    "Ton micro est resté muet : seuls les autres participants sont transcrits."
                )
            elif max(levels[1:]) < SEUIL_MUET_DB:
                outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)

    def _preciser_les_canaux(self, outcome: Outcome) -> None:
        """Says what the silence of the system loop meant."""
        if AVERTISSEMENT_SANS_BOUCLE not in outcome.warnings:
            return
        outcome.warnings.remove(AVERTISSEMENT_SANS_BOUCLE)
        if len(outcome.significant_voices()) > 1:
            return
        outcome.warnings.append(
            "Aucun son système capté et une seule voix entendue : si la réunion "
            "était en visio, les autres participants n'ont pas été enregistrés."
        )

    def _warn_about_coverage(self, outcome: Outcome) -> None:
        """Tells the user what the transcription lost."""
        from greffier.application.render import COUVERTURE_SUSPECTE, TROU_SIGNIFICATIF

        coverage = outcome.coverage
        if coverage <= 0:
            return
        gaps = [t for t in outcome.gaps(TROU_SIGNIFICATIF) if t.duration >= TROU_SIGNIFICATIF]
        perdu = sum(t.duration for t in gaps)
        if coverage < COUVERTURE_SUSPECTE:
            outcome.warnings.append(
                f"Couverture de {coverage * 100:.0f} % seulement : le modèle a "
                "probablement décroché sur une partie de la réunion. Le compte rendu "
                "en est averti, mais réécoute les passages qui te paraissent absents."
            )
        elif coverage < COUVERTURE_BASSE:
            outcome.warnings.append(
                f"Couverture de {coverage * 100:.0f} % : "
                f"{perdu / 60:.0f} min sans aucun texte. Des silences peuvent "
                "l'expliquer, mais vérifie qu'il ne manque rien d'important."
            )
        elif gaps:
            outcome.warnings.append(
                f"{len(gaps)} passage(s) sans texte, {perdu / 60:.0f} min au total. "
                "Un silence, ou du texte perdu : le compte rendu ne tranche pas."
            )

    def _warn_about_attendees(self, outcome: Outcome) -> None:
        """Says when the announced count contradicts what the audio holds."""
        if self.people is None:
            return
        entendues = len(outcome.significant_voices())
        if entendues == 0 or entendues == self.people:
            return
        outcome.warnings.append(
            f"{self.people} participants sont annoncés dans la configuration, "
            f"mais {entendues} voix distinctes ont été entendues. Le nombre "
            "annoncé l'emporte, donc des personnes ont pu être confondues. "
            "Laisse « participants » vide pour que le nombre soit déduit."
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
        membership = voix_domaine.stitch(voiceprints)
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

    def _recognise(self, audio: Path, turns: list[SpeakerTurn]) -> dict[str, str]:
        """Names from the voice bank, for people already known."""
        if self.extractor is None or self.bank is None:
            return {}
        connues = self.bank.people()
        if not connues:
            return {}
        trouves: dict[str, str] = {}
        per_voice: dict[str, list[Span]] = {}
        for turn in turns:
            per_voice.setdefault(turn.voice, []).append(turn.span)
        for voice, intervalles in per_voice.items():
            if sum(i.duration for i in intervalles) < MATERIAL_TO_RECOGNISE:
                continue
            extraits = self.extractor.extract_spans(audio, intervalles)
            if not extraits:
                continue
            match = voix_domaine.recognise(voix_domaine.aggregate(extraits), connues)
            if match and match.sure:
                trouves[voice] = match.name
        return trouves

    def _attribute_names(
        self,
        utterances: list[Utterance],
        turns: list[SpeakerTurn],
        depuis_banque: dict[str, str],
        outcome: Outcome,
    ) -> None:
        """Crosses the spoken names with the recognised voices.

        Both at once is a certainty. Either one alone stays a suggestion: better to ask
        than to write an invented name into minutes.
        """
        mentions = noms_domaine.spot_mentions(
            utterances, outcome.profil, self.not_first_names
        )
        attribution = noms_domaine.attribute(mentions, turns)

        for voice, name in depuis_banque.items():
            outcome.names[voice] = name

        for voice, trouve in attribution.certitudes.items():
            connu = depuis_banque.get(voice)
            if connu and connu.lower() != trouve.name.lower():
                outcome.warnings.append(
                    f"La voix {voice} est reconnue comme {connu} mais nommée {trouve.name} "
                    "pendant la réunion."
                )
                continue
            outcome.names[voice] = trouve.name

        for proposition in attribution.propositions:
            if proposition.voice not in outcome.names:
                outcome.propositions[proposition.voice] = proposition.name

    def _attach_voices(self, utterances: list[Utterance], turns: list[SpeakerTurn]) -> None:
        """Gives each utterance the voice that clearly holds it, else none."""
        for utterance in utterances:
            utterance.voice = voice_of(utterance.span, turns)

    def _join_namesakes(self, outcome: Outcome) -> None:
        """Folds onto one voice those that carry the same name.

        After attribution, not before: attribution is what gives the names, and here it
        is the name that says two voices are one person.
        """
        poids = {
            voice: sum(
                t.span.end - t.span.start
                for t in outcome.turns if t.voice == voice
            )
            for voice in set(outcome.names)
        }
        membership = noms_domaine.join_namesakes(outcome.names, poids)
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
        commencee_le: datetime | None = None,
        terminee_le: datetime | None = None,
    ) -> Outcome:
        self.hardware_events = list(hardware_events or [])
        outcome = Outcome(
            audio=audio,
            hardware_events=self.hardware_events,
            commencee_le=commencee_le,
            terminee_le=terminee_le,
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
        profil = profiles.pour(self.language)
        outcome.profil = profil
        outcome.utterances = collapse_loops([
            r for r in brutes
            if not is_boilerplate(r.text, profil) and not is_an_annotation(r.text)
        ])
        if outcome.words < MOTS_MINIMUM:
            raise ChainStopped(
                Phase.ECHEC,
                f"Transcription quasi vide ({outcome.words} mots) : "
                "aucun compte rendu n'a été rédigé.",
            )

        self._phase(Phase.LOCUTEURS, "Identification des locuteurs…")
        turns = self.diariser.segment(audio, self.people)
        turns = self._identify_voices(audio, turns)
        outcome.turns = turns
        self._attach_voices(outcome.utterances, turns)
        self._attribute_names(outcome.utterances, turns, self._recognise(audio, turns), outcome)
        self._join_namesakes(outcome)
        self._preciser_les_canaux(outcome)
        self._warn_about_coverage(outcome)
        self._warn_about_attendees(outcome)

        self._keep(audio, outcome)

        if self.writer is None:
            self._phase(Phase.TERMINE, "Transcription prête, aucun rédacteur configuré.")
            return outcome

        self._phase(Phase.REDACTION, f"{outcome.words} mots transcrits. Rédaction…")
        from greffier.application.render import (
            context_header,
            disclosure_header,
            hardware_header,
            reliability_header,
            render_transcript,
        )

        duration = outcome.turns[-1].span.end if outcome.turns else 0.0
        entendues = [
            v for v in outcome.significant_voices() if v
        ] + [v for v in outcome.names if v not in outcome.significant_voices()]
        header = (
            self._instructions_of(audio.stem)
            + context_header(audio.stem, duration,
                            names=[outcome.names[v] for v in entendues if v in outcome.names],
                            voix_entendues=len(entendues),
                            commencee_le=outcome.commencee_le,
                            terminee_le=outcome.terminee_le)
            + hardware_header(self.hardware_events)
            + reliability_header(outcome)
            + disclosure_header(self.disclosure)
            + self.context_header
        )
        outcome.minutes = self.writer.write_up(
            render_transcript(outcome, header)
        )
        titre_ecrit = titre_du_compte_rendu(outcome.minutes, "")
        if titre_ecrit:
            outcome.subject = (
                titre_ecrit.split(":", 1)[-1].strip() if ":" in titre_ecrit else titre_ecrit
            )

        self._keep(audio, outcome)

        if send and self.sender and self.recipient:
            self._phase(Phase.ENVOI, "Envoi du compte rendu…")
            try:
                self._send(audio, outcome)
            except Exception as trouble:  # noqa: BLE001
                outcome.warnings.append(
                    f"Compte rendu NON envoyé : {trouble} "
                    "Le compte rendu est gardé ; « greffier envoyer » réessaie."
                )
            else:
                outcome.envoye = True
        elif send:
            manque = ("aucun destinataire n'est configuré" if not self.recipient
                      else "aucun moyen d'envoi n'est configuré")
            outcome.warnings.append(
                f"Compte rendu NON envoyé : {manque}. "
                "« greffier envoyer » pour l'expédier, ou renseigne "
                "compte_rendu.destinataire dans la configuration."
            )

        self._phase(
            Phase.TERMINE,
            "Compte rendu envoyé." if outcome.envoye else "Compte rendu prêt, non envoyé.",
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
                garde = self.store.read(outcome.audio.stem).subject
                if garde:
                    outcome.subject = garde
            outcome.fichier_maitre = self.store.record(
                _as_stored_meeting(outcome, duration))
        if self.dossier_transcriptions is None:
            return
        transcription = self.dossier_transcriptions / f"{audio.stem}.txt"
        transcription.parent.mkdir(parents=True, exist_ok=True)
        transcription.write_text(render_transcript(outcome), encoding="utf-8")
        outcome.transcript_written = transcription
        if outcome.minutes and self.dossier_comptes_rendus is not None:
            minutes = self.dossier_comptes_rendus / f"{audio.stem}.md"
            minutes.parent.mkdir(parents=True, exist_ok=True)
            minutes.write_text(outcome.minutes, encoding="utf-8")
            outcome.compte_rendu_ecrit = minutes

    def _send(self, audio: Path, outcome: Outcome) -> None:
        """Sends the minutes, with no attachment."""
        assert self.sender is not None
        self.sender.send(
            self.recipient,
            titre_du_compte_rendu(
                outcome.minutes, f"Compte rendu de réunion — {audio.stem}"
            ),
            outcome.minutes,
            [],
        )

def _as_stored_meeting(outcome: Outcome, duration: float) -> StoredMeeting:
    """The master file, from what the chain produced."""
    return StoredMeeting(
        identifier=outcome.audio.stem,
        audio=outcome.audio,
        traitee_le=datetime.now(UTC),
        duration=duration,
        utterances=outcome.utterances,
        turns=outcome.turns,
        names=dict(outcome.names),
        propositions=dict(outcome.propositions),
        warnings=list(outcome.warnings),
        hardware_events=list(outcome.hardware_events),
        subject=outcome.subject,
        commencee_le=outcome.commencee_le,
        terminee_le=outcome.terminee_le,
    )
