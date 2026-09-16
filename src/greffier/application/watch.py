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
from dataclasses import dataclass, field
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
#: How long past its period a slice may wait for the room to go quiet, and
#: how often it looks meanwhile. A sentence cut in half at the boundary is
#: heard in two pieces, and the pieces do not always add up to the
#: sentence. Measured on SUMM-RE 032a with the turbo model, twenty seconds
#: of context (`docs/corpus.md`): 32.0 % of errors and 205 rare terms cut
#: on the clock, 28.8 % and 221 cut on silence, for 104 slices instead of
#: 119.
SLICE_SLACK_S = 3.0
SLICE_POLL = 0.25
#: Audio handed to the model before the slice, for the spelling to hold.
#: Measured on 2026-09-16 on SUMM-RE 032a (`docs/corpus.md`): none, twenty
#: and fifty seconds read alike with the large model (29.6 to 32.5 % of
#: errors, the rare terms unchanged), fifty seconds cost 17 s of card per
#: slice against 9 with twenty, and threw the turbo model, the one the live
#: thread runs, to 43 % of errors. Twenty keeps what a real meeting showed
#: the context does for a proper name ("sur Oasis" against "sur Asis"), at
#: half the price.
CONTEXT_S = 20.0

#: How often the watch listens for its own name between two full slices, and how
#: much audio it reads for it. Measured on a real machine: a full slice carried
#: fifty seconds of context so the spelling holds and cost 2 s, and one is taken
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

#: What the transcriber is told was said before each slice, so that it hears
#: her name: a call, in the shape a call takes. Put last, since a seed too
#: long for the model is cut from the front.
HER_NAME_SEED = "{name}, l'assistante, participe à la réunion."

def _within_the_slice(utterances: list[Utterance], boundary: float) -> list[Utterance]:
    """Keeps only what spills into the slice, rebased on it."""
    if boundary <= 0:
        return utterances
    kept = []
    for utterance in utterances:
        if utterance.span.end <= boundary:
            continue
        kept.append(Utterance(
            span=Span(
                max(0.0, utterance.span.start - boundary),
                utterance.span.end - boundary,
            ),
            text=utterance.text, voice=utterance.voice, source=utterance.source,
            confidence=utterance.confidence,
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
    locate: Callable[[], Position | None] | None = None
    follower: Follower | None = None
    preparer: outbound.AudioRecorder | None = None
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
    _speech_end: SpeechEnd = field(default_factory=SpeechEnd, repr=False)
    initiative: bool = False
    material_before_asking: float = 30.0
    slice_period: float = SLICE_PERIOD
    processed: float = 0.0
    vu: float | None = None
    #: True while a slice past its period waits for the room to go quiet.
    holding_the_slice: bool = False
    _last_listened: float = 0.0
    _held_call: str | None = None

    def _current_prompt_seed(self) -> str:
        """The seed for this slice, context re-read if it changed, her name in it.

        Her name is what the whole listening pass looks for, and a first name
        at the start of a sentence is what a model hears worst: measured on
        the synthesised voices, « Lucie, où en est la recette ? » came back
        « Ici, où en est la recette » two times in ten. The seed is what the
        model believes was said just before; a sentence that calls her by
        name, in it, brought the ten back whole, and « Vocabulaire : Lucie »
        alone did not.
        """
        seed = self.prompt_seed
        if self.reread_the_seed is not None:
            try:
                fresh_one = self.reread_the_seed()
            except OSError:
                fresh_one = ""
            if fresh_one and fresh_one != self.prompt_seed:
                self.prompt_seed = fresh_one
            seed = self.prompt_seed
        if self.assistant_of is not None and self.assistant_of.name:
            return f"{seed} {HER_NAME_SEED.format(name=self.assistant_of.name)}".strip()
        return seed

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
        self, where_: Position, job: Path, let_speak: bool = True
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
        start = max(0.0, self.processed - where_.offset - OVERLAP, where_.written - SLICE_MAXIMUM)
        if where_.written - start < SLICE_MINIMUM_S:
            return []
        slice_ = extract_slice(where_.chunk, start, where_.written, job / "tranche.wav")
        if slice_ is None:
            return []
        depart = max(0.0, start - CONTEXT_S)
        with_context = slice_ if depart >= start else (
            extract_slice(where_.chunk, depart, where_.written, job / "fenetre.wav")
            or slice_
        )
        to_transcribe = with_context
        if self.preparer is not None:
            to_transcribe = self.preparer.prepare_transcript(
                with_context, job / "tranche-niveau.wav"
            )
        try:
            utterances = self.transcriber.transcribe(
                to_transcribe, self.language, self._current_prompt_seed()
            )
        except (RuntimeError, OSError):
            return []
        utterances = _within_the_slice(utterances, start - depart)
        self.processed = where_.offset + where_.written
        if self.interrogate is not None:
            for utterance in utterances:
                with contextlib.suppress(OSError):
                    self.interrogate(utterance.text)
        offset = where_.offset + start
        rebased = [
            Utterance(
                span=Span(
                    r.span.start + offset, r.span.end + offset
                ),
                text=r.text, voice=r.voice, source=r.source, confidence=r.confidence,
            )
            for r in utterances
        ]
        fresh = self.watch_rules.listen(rebased)
        self.publish(fresh)
        if self.follower is not None:
            self.follower.take_in(slice_, utterances, offset)
        if let_speak:
            self.assistant_turn(rebased, self.processed)
        return fresh

    def listening_turn(self, where_: Position, job: Path, prompted: bool = False) -> bool:
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
        her = self.assistant_of
        if (her is None or her.brain is None or self.transcriber is None
                or her.busy or not her.manners.active):
            return False
        if where_.overall - self._last_listened < (LISTENING_GAP if prompted else LISTENING_PERIOD):
            return False
        self._last_listened = where_.overall
        start = max(0.0, where_.written - LISTENING_S)
        if where_.written - start < SLICE_MINIMUM_S:
            return False
        chunk = extract_slice(where_.chunk, start, where_.written, job / "ecoute.wav")
        if chunk is None:
            return False
        try:
            heard = self.transcriber.transcribe(
                chunk, self.language, self._current_prompt_seed()
            )
        except (RuntimeError, OSError):
            return True
        if prompted and self._speech_end.resumed_after(where_.overall):
            # The quiet was a breath in the middle of the question, not its
            # end: the room went on talking while this pass transcribed. What
            # it heard is half a question, and the model answers « RIEN » to
            # half a question (measured on the bench). The real end will
            # prompt a pass that hears the whole of it.
            return True
        offset = where_.offset + start
        # A pass on the clock may land in the middle of a sentence, and what
        # runs into the end of the window waits for the next pass to be whole.
        # A prompted pass comes half a second after the room went quiet, and
        # the model's own end stamps overshoot by more than the margin: judged
        # by the clock, it dropped every question it was prompted for.
        still_talking = float("inf") if prompted else (where_.written - start) - STILL_TALKING_S
        rebased = [
            Utterance(
                span=Span(r.span.start + offset, r.span.end + offset),
                text=r.text, voice=r.voice, source=r.source, confidence=r.confidence,
            )
            for r in heard
            if r.span.end <= still_talking
        ]
        self.assistant_turn(self._whole_calls(rebased, her.name), where_.overall,
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

    def _apply_the_buttons(self, out_loud: bool, of_its_own: bool) -> None:
        """Follows the window's two buttons, without restarting anything.

        Going quiet is immediate, current sentence included. The initiative is re-read
        here and not at startup, or its button would only take effect at the next
        meeting.
        """
        if self.assistant_of is None:
            return
        her = self.assistant_of
        self.initiative = of_its_own
        if not out_loud and her.voice is not None:
            her.voice.go_quiet()
            her.voice = None
        elif out_loud and her.voice is None and self.give_voice_back is not None:
            her.voice = self.give_voice_back()

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
        clipboard_read_at = float("-inf")
        try:
            while still_running():
                now = since()
                if now - clipboard_read_at >= CLIPBOARD_PERIOD:
                    clipboard_read_at = now
                    self.clipboard_turn(now)
                where_ = self.locate() if self.locate is not None else None
                if where_ is not None and self._is_time(where_):
                    self.transcription_turn(where_, job)
                # A slice waiting for a quiet moment looks four times a second:
                # the moment is worth a quarter of a second, not two.
                pause(SLICE_POLL if self.holding_the_slice else CLIPBOARD_PERIOD)
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
        end = self._speech_end
        prompted = False
        pass_: threading.Thread | None = None
        while True:
            where_ = self.locate() if self.locate is not None else None
            if where_ is not None:
                # Whatever it was: the meeting goes on without this pass.
                with contextlib.suppress(Exception):
                    prompted = prompted or self._somebody_just_stopped(where_, end)
                    # The pass runs aside, so that the levels are still watched
                    # while it does: blocked behind a pass of three seconds, the
                    # watcher missed the end of every question it was meant to
                    # catch, and the clock had it back.
                    if (pass_ is None or not pass_.is_alive()) and self._due(where_, prompted, end):
                        pass_ = threading.Thread(
                            target=self._one_listening_pass, args=(where_, job, prompted),
                            daemon=True,
                        )
                        pass_.start()
                        prompted = False
            if stop.wait(LISTENING_POLL):
                if pass_ is not None:
                    pass_.join(timeout=LISTENING_S * 4)
                return

    def _due(self, where_: Position, prompted: bool, end: SpeechEnd) -> bool:
        """Whether the clock, or somebody stopping, calls for a pass now.

        Not on the clock while nobody has spoken since the last pass: the
        room is quiet, the pass would read the same eight seconds again, and
        on a small card every pass slows the one that matters.
        """
        if prompted:
            return where_.overall - self._last_listened >= LISTENING_GAP
        if not end.spoken_since(self._last_listened):
            return False
        return where_.overall - self._last_listened >= LISTENING_PERIOD

    def _one_listening_pass(self, where_: Position, job: Path, prompted: bool) -> None:
        with contextlib.suppress(Exception):
            self.listening_turn(where_, job, prompted=prompted)

    def _somebody_just_stopped(self, where_: Position, end: SpeechEnd) -> bool:
        """Whether a speech has just ended at this position, from the levels."""
        if self.speaking is None:
            return False
        talking = self.speaking(where_)
        if talking is None:
            return False
        return end.note(where_.overall, talking)

    def last_pass(self, job: Path) -> list[Suggestion]:
        """Transcribes what was left when the meeting stopped."""
        where_ = self.locate() if self.locate is not None else None
        if where_ is None or where_.overall - self.processed < SLICE_MINIMUM_S:
            return []
        return self.transcription_turn(where_, job, let_speak=False)

    def _is_time(self, where_: Position) -> bool:
        """Is it time to transcribe?

        Past the period, yes, unless somebody is talking and the slack is
        not spent: the slice then waits for the next quiet moment, so that
        the sentence under way is heard whole rather than in two pieces.
        """
        advance = where_.overall - self.processed
        stalls = self.vu is not None and abs(where_.written - self.vu) < 0.05
        self.vu = where_.written
        if advance >= self.slice_period:
            self.holding_the_slice = self._still_talking(where_, advance)
            return not self.holding_the_slice
        self.holding_the_slice = False
        return stalls and advance >= SLICE_MINIMUM_S

    def _still_talking(self, where_: Position, advance: float) -> bool:
        """Whether the room talks at this moment, with slack left to wait for it."""
        if self.speaking is None or advance >= self.slice_period + SLICE_SLACK_S:
            return False
        try:
            return bool(self.speaking(where_))
        except Exception:  # noqa: BLE001 -- a level that cannot be read is no reason to wait
            return False
