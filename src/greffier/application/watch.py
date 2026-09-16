"""Watching during the meeting, never acting alone.

Everything it finds is a suggestion, written to a log and validated later. The
only thing it does on its own is speak, and only when called by name.
"""

from __future__ import annotations

import contextlib
import json
import platform
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from greffier.application.follow import SLICE_MINIMUM_S, Follower, Position
from greffier.application.take_part import AssistantSettings
from greffier.domain.channels import SpeechEnd
from greffier.domain.instructions import Suggestion, WatchRules
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Opening, called_by_name
from greffier.ports import outbound

SYSTEM = platform.system()

AWAITING_AN_ANSWER = frozenset({
    Because.INDISTINCT_VOICE,
    Because.DECISION_WITHOUT_FOLLOW_UP,
    Because.QUESTION_WITHOUT_ANSWER,
    Because.GAP_WITH_A_DOCUMENT,
    Because.CONTRIBUTION,
})

CLIPBOARD_PERIOD = 2.0
SLICE_PERIOD = 30.0
OVERLAP = 5.0
SLICE_MAXIMUM = 90.0
CONTEXT_S = 50.0

#: How often the watch listens for its own name between two full slices, and how
#: much audio it reads for it. Measured on a real machine: a full slice carries
#: fifty seconds of context so the spelling holds and costs 2 s, and one is taken
#: every ten seconds, so being called cost up to fifteen seconds before a word
#: came back. Eight seconds with no context cost 0.8 s.
LISTENING_PERIOD = 3.0
LISTENING_S = 8.0

#: The listening thread looks at the room's level this often, and listens the
#: moment somebody has just stopped talking rather than on the clock: measured
#: on the bench, the clock alone spotted a call 0.8 to 5.9 s after the
#: question ended. Two passes are never closer than the gap, however prompted.
LISTENING_POLL = 0.25
LISTENING_GAP = 1.0

#: A sentence that runs into the end of the window is a sentence still being
#: said: half a question answered is worse than a question answered late.
STILL_TALKING_S = 0.4

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

#: What ends a sentence the model has finished writing down.
_SENTENCE_ENDS = (".", "?", "!", "…", "»")

def _finished(text: str) -> bool:
    """Whether the transcriber closed the sentence."""
    return text.rstrip().endswith(_SENTENCE_ENDS)

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
    reread_the_seed: Callable[[], str] | None = None
    assistant_of: AssistantSettings | None = None
    reread_participation: Callable[[], tuple[bool, bool]] | None = None
    give_voice_back: Callable[[], Any] | None = None
    #: Whether somebody is talking at this position, None when it cannot be
    #: told: the levels of the file being written, read by whoever wires it.
    speaking: Callable[[Position], bool | None] | None = None
    initiative: bool = False
    material_before_asking: float = 30.0
    slice_period: float = SLICE_PERIOD
    traite: float = 0.0
    vu: float | None = None
    _last_listened: float = 0.0
    _held_call: str | None = None

    def _current_prompt_seed(self) -> str:
        """The seed for this slice, context re-read if it changed."""
        if self.reread_the_seed is None:
            return self.prompt_seed
        try:
            fraiche = self.reread_the_seed()
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
        self, ou: Position, job: Path, let_speak: bool = True
    ) -> list[Suggestion]:
        """Transcribes what has been recorded since the last slice.

        `laisser_parler` false on the last pass: the meeting is over, and the
        assistant answering out loud in a room that has just been told the
        meeting is finished would be a strange thing to watch. The sentence is
        still transcribed and still lands in the minutes, only the voice is
        held back.
        """
        if self.transcriber is None:
            return []
        start = max(0.0, self.traite - ou.offset - OVERLAP, ou.written - SLICE_MAXIMUM)
        if ou.written - start < SLICE_MINIMUM_S:
            return []
        slice_ = extract_slice(ou.chunk, start, ou.written, job / "tranche.wav")
        if slice_ is None:
            return []
        depart = max(0.0, start - CONTEXT_S)
        with_context = slice_ if depart >= start else (
            extract_slice(ou.chunk, depart, ou.written, job / "fenetre.wav")
            or slice_
        )
        to_transcribe = with_context
        if self.preparateur is not None:
            to_transcribe = self.preparateur.prepare_transcript(
                with_context, job / "tranche-niveau.wav"
            )
        try:
            utterances = self.transcriber.transcribe(
                to_transcribe, self.language, self._current_prompt_seed()
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
        if let_speak:
            self.assistant_turn(recalees, self.traite)
        return fresh

    def listening_turn(self, ou: Position, job: Path, prompted: bool = False) -> bool:
        """Answers a call without waiting for the next slice.

        A full slice is built for the thread: fifty seconds of context so the
        spelling holds, one every ten seconds. Being called therefore cost up to
        fifteen seconds before a word came back, where a few were expected: ten
        of waiting, two of transcription, three for the answer to come back.

        This pass reads the last eight seconds alone, with no context, and looks
        only for the assistant's own name. The remark it hands over carries a
        subject, so the same call arriving again in the full slice is refused as
        already answered rather than answered twice.

        `prompted` when somebody has just stopped talking: the pass then waits
        for the gap rather than the period. True when something was listened to.
        """
        lui = self.assistant_of
        if (lui is None or lui.cerveau is None or self.transcriber is None
                or lui.busy or not lui.manners.active):
            return False
        if ou.overall - self._last_listened < (LISTENING_GAP if prompted else LISTENING_PERIOD):
            return False
        self._last_listened = ou.overall
        start = max(0.0, ou.written - LISTENING_S)
        if ou.written - start < SLICE_MINIMUM_S:
            return False
        chunk = extract_slice(ou.chunk, start, ou.written, job / "ecoute.wav")
        if chunk is None:
            return False
        try:
            heard = self.transcriber.transcribe(
                chunk, self.language, self._current_prompt_seed()
            )
        except (RuntimeError, OSError):
            return True
        offset = ou.offset + start
        # A pass on the clock may land in the middle of a sentence, and what
        # runs into the end of the window waits for the next pass to be whole.
        # A prompted pass comes half a second after the room went quiet, and
        # the model's own end stamps overshoot by more than the margin: judged
        # by the clock, it dropped every question it was prompted for.
        still_talking = float("inf") if prompted else (ou.written - start) - STILL_TALKING_S
        recalees = [
            Utterance(
                span=Span(r.span.start + offset, r.span.end + offset),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in heard
            if r.span.end <= still_talking
        ]
        self.assistant_turn(self._whole_calls(recalees, lui.name), ou.overall,
                            only_when_called=True)
        return True

    def _whole_calls(self, utterances: list[Utterance], name: str) -> list[Utterance]:
        """Holds back a call whose sentence is not finished, once.

        Somebody who pauses half a second in the middle of a question has
        stopped talking as far as the levels can tell, and the pass then reads
        "Lucie, à quel jour" with no end to it. A call with no full stop waits
        for the next pass; the same words again mean the speaker really did
        stop, and the call goes through as it is.
        """
        kept: list[Utterance] = []
        for utterance in utterances:
            text = utterance.text.strip()
            unfinished = called_by_name(text, name) and not _finished(text)
            if unfinished and text != self._held_call:
                self._held_call = text
                continue
            kept.append(utterance)
        return kept

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
        retained = self.assistant_of.turn(
            utterances, now,
            turns=self._turn_bounds(),
            occasions=[] if only_when_called else self._voices_to_ask_about(now),
        )
        if retained is None:
            if self.initiative and not only_when_called:
                self.assistant_of.look_for_a_contribution_aside(now)
            return
        if retained.because in AWAITING_AN_ANSWER:
            self.assistant_of.awaiting = retained
        self.assistant_of.answer_aside(retained, now)

    def _apply_the_buttons(self, out_loud: bool, de_lui_meme: bool) -> None:
        """Follows the window's two buttons, without restarting anything.

        Going quiet is immediate, current sentence included. The initiative is re-read
        here and not at startup, or its button would only take effect at the next
        meeting.
        """
        if self.assistant_of is None:
            return
        lui = self.assistant_of
        self.initiative = de_lui_meme
        if not out_loud and lui.voice is not None:
            lui.voice.go_quiet()
            lui.voice = None
        elif out_loud and lui.voice is None and self.give_voice_back is not None:
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
        stop = threading.Event()
        listener = threading.Thread(target=self._listen, args=(job, stop), daemon=True)
        listener.start()
        try:
            while still_running():
                self.clipboard_turn(since())
                ou = self.situer() if self.situer is not None else None
                if ou is not None and self._is_time(ou):
                    self.transcription_turn(ou, job)
                pause(CLIPBOARD_PERIOD)
        finally:
            stop.set()
            listener.join(timeout=LISTENING_S * 4)
        self.last_pass(job)
        if self.assistant_of is not None:
            self.assistant_of.stop()
        return self.watch_rules.propositions

    def _listen(self, job: Path, stop: threading.Event) -> None:
        """The listening pass, on a thread of its own.

        It used to take its turn in the loop above, between two clipboard
        reads: a call was heard every four seconds at best, and not at all
        while a full slice was being transcribed. Measured on a loaded
        machine, the assistant answered a question twenty seconds after the
        next one had been asked. Here it listens at its own pace whatever the
        slice is doing; the slice still answers a call the pass missed.
        """
        end = SpeechEnd()
        prompted = False
        pass_: threading.Thread | None = None
        while True:
            ou = self.situer() if self.situer is not None else None
            if ou is not None:
                # Whatever it was: the meeting goes on without this pass.
                with contextlib.suppress(Exception):
                    prompted = prompted or self._somebody_just_stopped(ou, end)
                    # The pass runs aside, so that the levels are still watched
                    # while it does: blocked behind a pass of three seconds, the
                    # watcher missed the end of every question it was meant to
                    # catch, and the clock had it back.
                    if (pass_ is None or not pass_.is_alive()) and self._due(ou, prompted, end):
                        pass_ = threading.Thread(
                            target=self._one_listening_pass, args=(ou, job, prompted),
                            daemon=True,
                        )
                        pass_.start()
                        prompted = False
            if stop.wait(LISTENING_POLL):
                if pass_ is not None:
                    pass_.join(timeout=LISTENING_S * 4)
                return

    def _due(self, ou: Position, prompted: bool, end: SpeechEnd) -> bool:
        """Whether the clock, or somebody stopping, calls for a pass now.

        Not on the clock while nobody has spoken since the last pass: the
        room is quiet, the pass would read the same eight seconds again, and
        on a small card every pass slows the one that matters.
        """
        if prompted:
            return ou.overall - self._last_listened >= LISTENING_GAP
        if not end.spoken_since(self._last_listened):
            return False
        return ou.overall - self._last_listened >= LISTENING_PERIOD

    def _one_listening_pass(self, ou: Position, job: Path, prompted: bool) -> None:
        with contextlib.suppress(Exception):
            self.listening_turn(ou, job, prompted=prompted)

    def _somebody_just_stopped(self, ou: Position, end: SpeechEnd) -> bool:
        """Whether a speech has just ended at this position, from the levels."""
        if self.speaking is None:
            return False
        talking = self.speaking(ou)
        if talking is None:
            return False
        return end.note(ou.overall, talking)

    def last_pass(self, job: Path) -> list[Suggestion]:
        """Transcribes what was left when the meeting stopped."""
        ou = self.situer() if self.situer is not None else None
        if ou is None or ou.overall - self.traite < SLICE_MINIMUM_S:
            return []
        return self.transcription_turn(ou, job, let_speak=False)

    def _is_time(self, ou: Position) -> bool:
        """Is it time to transcribe?"""
        avance = ou.overall - self.traite
        stagne = self.vu is not None and abs(ou.written - self.vu) < 0.05
        self.vu = ou.written
        if avance >= self.slice_period:
            return True
        return stagne and avance >= SLICE_MINIMUM_S
