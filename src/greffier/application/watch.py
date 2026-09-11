"""Watching during the meeting, never acting alone.

Everything it finds is a suggestion, written to a log and validated later. The
only thing it does on its own is speak, and only when called by name.
"""

from __future__ import annotations

import contextlib
import json
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from greffier.application.follow import TRANCHE_MINIMALE_S, Follower, Position
from greffier.application.take_part import AssistantSettings
from greffier.domain.instructions import Suggestion, WatchRules
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Opening, called_by_name
from greffier.ports import outbound

SYSTEM = platform.system()

ATTENDENT_UNE_REPONSE = frozenset({
    Because.INDISTINCT_VOICE,
    Because.DECISION_WITHOUT_FOLLOW_UP,
    Because.QUESTION_WITHOUT_ANSWER,
    Because.GAP_WITH_A_DOCUMENT,
    Because.CONTRIBUTION,
})

PERIODE_PRESSE_PAPIER = 2.0
SLICE_PERIOD = 30.0
OVERLAP = 5.0
TRANCHE_MAXIMALE = 90.0
CONTEXTE_S = 50.0

#: How often the watch listens for its own name between two full slices, and how
#: much audio it reads for it. Measured on a real machine: a full slice carries
#: fifty seconds of context so the spelling holds and costs 2 s, and one is taken
#: every ten seconds, so being called cost up to fifteen seconds before a word
#: came back. Eight seconds with no context cost 0.8 s.
LISTENING_PERIOD = 3.0
LISTENING_S = 8.0

def _within_the_slice(utterances: list[Utterance], frontiere: float) -> list[Utterance]:
    """Keeps only what spills into the slice, rebased on it."""
    if frontiere <= 0:
        return utterances
    kept = []
    for utterance in utterances:
        if utterance.span.end <= frontiere:
            continue
        kept.append(Utterance(
            span=Span(
                max(0.0, utterance.span.start - frontiere),
                utterance.span.end - frontiere,
            ),
            text=utterance.text, voice=utterance.voice, source=utterance.source,
        ))
    return kept

def read_the_clipboard() -> str:
    """Clipboard contents, or empty when the system will not give them."""
    commands = {
        "Darwin": ["pbpaste"],
        "Linux": (["wl-paste"] if _exists("wl-paste")
                  else ["xclip", "-o", "-selection", "clipboard"]),
        "Windows": ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
    }
    command = commands.get(SYSTEM)
    if not command:
        return ""
    try:
        return subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""

def _exists(programme: str) -> bool:
    import shutil

    return shutil.which(programme) is not None

def extract_slice(audio: Path, start: float, end: float, destination: Path) -> Path | None:
    """Cuts a chunk out of a recording **while it is being written**."""
    if not audio.exists() or audio.stat().st_size < 1024:
        return None
    outcome = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
         "-i", str(audio), "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, check=False,
    )
    if outcome.returncode != 0 or not destination.exists():
        return None
    return destination if destination.stat().st_size > 1024 else None

@dataclass
class Watcher:
    """Runs the watch as long as the meeting is recording."""

    watch_rules: WatchRules
    log: Path
    transcriber: outbound.Transcriber | None = None
    situer: Callable[[], Position | None] | None = None
    follower: Follower | None = None
    preparateur: outbound.AudioRecorder | None = None
    language: str = "fr"
    interrogate: Callable[[str], None] | None = None
    prompt_seed: str = ""
    relire_l_amorce: Callable[[], str] | None = None
    assistant_of: AssistantSettings | None = None
    reread_participation: Callable[[], tuple[bool, bool]] | None = None
    give_voice_back: Callable[[], Any] | None = None
    initiative: bool = False
    material_before_asking: float = 30.0
    slice_period: float = SLICE_PERIOD
    traite: float = 0.0
    vu: float | None = None
    _last_listened: float = 0.0

    def _current_prompt_seed(self) -> str:
        """The seed for this slice, context re-read if it changed."""
        if self.relire_l_amorce is None:
            return self.prompt_seed
        try:
            fraiche = self.relire_l_amorce()
        except OSError:
            return self.prompt_seed
        if fraiche and fraiche != self.prompt_seed:
            self.prompt_seed = fraiche
        return self.prompt_seed

    def publish(self, fresh: list[Suggestion]) -> None:
        """Appends to the log, one suggestion per line."""
        if not fresh:
            return
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as stream:
            for proposition in fresh:
                stream.write(json.dumps({
                    "genre": proposition.kind.value,
                    "texte": proposition.text,
                    "instant": round(proposition.at_instant, 1),
                    "origine": proposition.origin.value,
                    "contexte": proposition.context,
                }, ensure_ascii=False) + "\n")

    def clipboard_turn(self, at_instant: float) -> list[Suggestion]:
        content = read_the_clipboard()
        fresh = self.watch_rules.paste(content, at_instant) if content else []
        self.publish(fresh)
        return fresh

    def transcription_turn(
        self, ou: Position, job: Path, laisser_parler: bool = True
    ) -> list[Suggestion]:
        """Transcribes what has been recorded since the last slice.

        `laisser_parler` false on the last pass: the meeting is over, and the
        assistant answering out loud in a room that has just been told the
        meeting is finished would be a strange thing to watch. The sentence is
        still transcribed and still lands in the minutes — only the voice is
        held back.
        """
        if self.transcriber is None:
            return []
        start = max(0.0, self.traite - ou.offset - OVERLAP, ou.written - TRANCHE_MAXIMALE)
        if ou.written - start < TRANCHE_MINIMALE_S:
            return []
        slice_ = extract_slice(ou.morceau, start, ou.written, job / "tranche.wav")
        if slice_ is None:
            return []
        depart = max(0.0, start - CONTEXTE_S)
        avec_contexte = slice_ if depart >= start else (
            extract_slice(ou.morceau, depart, ou.written, job / "fenetre.wav")
            or slice_
        )
        a_transcrire = avec_contexte
        if self.preparateur is not None:
            a_transcrire = self.preparateur.prepare_transcript(
                avec_contexte, job / "tranche-niveau.wav"
            )
        try:
            utterances = self.transcriber.transcribe(
                a_transcrire, self.language, self._current_prompt_seed()
            )
        except (RuntimeError, OSError):
            return []
        utterances = _within_the_slice(utterances, start - depart)
        self.traite = ou.offset + ou.written
        if self.interrogate is not None:
            for utterance in utterances:
                with contextlib.suppress(OSError):
                    self.interrogate(utterance.text)
        offset = ou.offset + start
        recalees = [
            Utterance(
                span=Span(
                    r.span.start + offset, r.span.end + offset
                ),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in utterances
        ]
        fresh = self.watch_rules.listen(recalees)
        self.publish(fresh)
        if self.follower is not None:
            self.follower.take_in(slice_, utterances, offset)
        if laisser_parler:
            self.assistant_turn(recalees, self.traite)
        return fresh

    def listening_turn(self, ou: Position, job: Path) -> None:
        """Answers a call without waiting for the next slice.

        A full slice is built for the thread: fifty seconds of context so the
        spelling holds, one every ten seconds. Being called therefore cost up to
        fifteen seconds before a word came back, where a few were expected: ten
        of waiting, two of transcription, three for the answer to come back.

        This pass reads the last eight seconds alone, with no context, and looks
        only for the assistant's own name. The remark it hands over carries a
        subject, so the same call arriving again in the full slice is refused as
        already answered rather than answered twice.
        """
        lui = self.assistant_of
        if (lui is None or lui.cerveau is None or self.transcriber is None
                or lui.busy or not lui.manners.active):
            return
        if ou.overall - self._last_listened < LISTENING_PERIOD:
            return
        self._last_listened = ou.overall
        start = max(0.0, ou.written - LISTENING_S)
        if ou.written - start < TRANCHE_MINIMALE_S:
            return
        morceau = extract_slice(ou.morceau, start, ou.written, job / "ecoute.wav")
        if morceau is None:
            return
        try:
            entendu = self.transcriber.transcribe(
                morceau, self.language, self._current_prompt_seed()
            )
        except (RuntimeError, OSError):
            return
        offset = ou.offset + start
        recalees = [
            Utterance(
                span=Span(r.span.start + offset, r.span.end + offset),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in entendu
        ]
        self.assistant_turn(recalees, ou.overall, only_when_called=True)

    def assistant_turn(
        self, utterances: list[Utterance], now: float, only_when_called: bool = False
    ) -> None:
        """Lets the assistant decide whether it has anything to say.

        `only_when_called` on the listening pass: it exists to answer its own
        name quickly, and nothing else. Letting it look for something to add
        there would call the model every three seconds.
        """
        if self.assistant_of is None:
            return
        if only_when_called and not any(
            called_by_name(u.text, self.assistant_of.name) for u in utterances
        ):
            return
        if self.reread_participation is not None:
            with contextlib.suppress(OSError):
                self._apply_the_buttons(*self.reread_participation())
        retenue = self.assistant_of.turn(
            utterances, now,
            turns=self._turn_bounds(),
            occasions=[] if only_when_called else self._voices_to_ask_about(now),
        )
        if retenue is None:
            if self.initiative and not only_when_called:
                self.assistant_of.look_for_a_contribution_aside(now)
            return
        if retenue.because in ATTENDENT_UNE_REPONSE:
            self.assistant_of.awaiting = retenue
        self.assistant_of.answer_aside(retenue, now)

    def _apply_the_buttons(self, a_voix_haute: bool, de_lui_meme: bool) -> None:
        """Follows the window's two buttons, without restarting anything.

        Going quiet is immediate, current sentence included. The initiative is re-read
        here and not at startup, or its button would only take effect at the next
        meeting.
        """
        if self.assistant_of is None:
            return
        lui = self.assistant_of
        self.initiative = de_lui_meme
        if not a_voix_haute and lui.voice is not None:
            lui.voice.go_quiet()
            lui.voice = None
        elif a_voix_haute and lui.voice is None and self.give_voice_back is not None:
            lui.voice = self.give_voice_back()

    def _turn_bounds(self) -> list[tuple[float, float]]:
        """The displayed speaker turns, to measure how dense the discussion is."""
        if self.follower is None:
            return []
        return [(t.span.start, t.span.end) for t in self.follower.thread.turns]

    def _voices_to_ask_about(self, now: float) -> list[Opening]:
        """A voice that spoke at length without anyone knowing whose it is."""
        if self.follower is None or self.assistant_of is None or not self.initiative:
            return []
        for voice in self.follower.thread.voice.values():
            if (voice.name is None and voice.nameable
                    and voice.seconds >= self.material_before_asking):
                return [self.assistant_of.ask_who_is_speaking(voice.identifier, now)]
        return []

    def loop(
        self,
        still_running: Callable[[], bool],
        since: Callable[[], float],
        job: Path,
        pause: Callable[[float], None] = time.sleep,
    ) -> list[Suggestion]:
        """Runs until the recording ends."""
        while still_running():
            self.clipboard_turn(since())
            ou = self.situer() if self.situer is not None else None
            if ou is not None and self._is_time(ou):
                self.transcription_turn(ou, job)
            elif ou is not None:
                self.listening_turn(ou, job)
            pause(PERIODE_PRESSE_PAPIER)
        self.last_pass(job)
        if self.assistant_of is not None:
            self.assistant_of.stop()
        return self.watch_rules.propositions

    def last_pass(self, job: Path) -> list[Suggestion]:
        """Transcribes what was left when the meeting stopped."""
        ou = self.situer() if self.situer is not None else None
        if ou is None or ou.overall - self.traite < TRANCHE_MINIMALE_S:
            return []
        return self.transcription_turn(ou, job, laisser_parler=False)

    def _is_time(self, ou: Position) -> bool:
        """Is it time to transcribe?"""
        avance = ou.overall - self.traite
        stagne = self.vu is not None and abs(ou.written - self.vu) < 0.05
        self.vu = ou.written
        if avance >= self.slice_period:
            return True
        return stagne and avance >= TRANCHE_MINIMALE_S
