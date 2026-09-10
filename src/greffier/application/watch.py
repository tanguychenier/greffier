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
from greffier.domain.participation import Because, Opening
from greffier.ports import outbound

SYSTEM = platform.system()

ATTENDENT_UNE_REPONSE = frozenset({
    Because.VOIX_INDISTINCTE,
    Because.DECISION_SANS_SUITE,
    Because.QUESTION_SANS_REPONSE,
    Because.ECART_AVEC_UN_DOCUMENT,
    Because.CONTRIBUTION,
})

PERIODE_PRESSE_PAPIER = 2.0
SLICE_PERIOD = 30.0
OVERLAP = 5.0
TRANCHE_MAXIMALE = 90.0
CONTEXTE_S = 50.0

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

    def publish(self, nouvelles: list[Suggestion]) -> None:
        """Appends to the log, one suggestion per line."""
        if not nouvelles:
            return
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as flux:
            for proposition in nouvelles:
                flux.write(json.dumps({
                    "genre": proposition.kind.value,
                    "texte": proposition.text,
                    "instant": round(proposition.at_instant, 1),
                    "origine": proposition.origine.value,
                    "contexte": proposition.context,
                }, ensure_ascii=False) + "\n")

    def clipboard_turn(self, at_instant: float) -> list[Suggestion]:
        content = read_the_clipboard()
        nouvelles = self.watch_rules.paste(content, at_instant) if content else []
        self.publish(nouvelles)
        return nouvelles

    def transcription_turn(self, ou: Position, job: Path) -> list[Suggestion]:
        """Transcribes what has been recorded since the last slice."""
        if self.transcriber is None:
            return []
        start = max(0.0, self.traite - ou.decalage - OVERLAP, ou.ecrit - TRANCHE_MAXIMALE)
        if ou.ecrit - start < TRANCHE_MINIMALE_S:
            return []
        tranche = extract_slice(ou.morceau, start, ou.ecrit, job / "tranche.wav")
        if tranche is None:
            return []
        depart = max(0.0, start - CONTEXTE_S)
        avec_contexte = tranche if depart >= start else (
            extract_slice(ou.morceau, depart, ou.ecrit, job / "fenetre.wav")
            or tranche
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
        self.traite = ou.decalage + ou.ecrit
        if self.interrogate is not None:
            for utterance in utterances:
                with contextlib.suppress(OSError):
                    self.interrogate(utterance.text)
        decalage = ou.decalage + start
        recalees = [
            Utterance(
                span=Span(
                    r.span.start + decalage, r.span.end + decalage
                ),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in utterances
        ]
        nouvelles = self.watch_rules.listen(recalees)
        self.publish(nouvelles)
        if self.follower is not None:
            self.follower.take_in(tranche, utterances, decalage)
        self.assistant_turn(recalees, self.traite)
        return nouvelles

    def assistant_turn(self, utterances: list[Utterance], now: float) -> None:
        """Lets the assistant decide whether it has anything to say."""
        if self.assistant_of is None:
            return
        if self.reread_participation is not None:
            with contextlib.suppress(OSError):
                self._apply_the_buttons(*self.reread_participation())
        retenue = self.assistant_of.turn(
            utterances, now,
            turns=self._turn_bounds(),
            occasions=self._voices_to_ask_about(now),
        )
        if retenue is None:
            if self.initiative:
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
        depuis: Callable[[], float],
        job: Path,
        pause: Callable[[float], None] = time.sleep,
    ) -> list[Suggestion]:
        """Runs until the recording ends."""
        while still_running():
            self.clipboard_turn(depuis())
            ou = self.situer() if self.situer is not None else None
            if ou is not None and self._is_time(ou):
                self.transcription_turn(ou, job)
            pause(PERIODE_PRESSE_PAPIER)
        self.last_pass(job)
        return self.watch_rules.propositions

    def last_pass(self, job: Path) -> list[Suggestion]:
        """Transcribes what was left when the meeting stopped."""
        ou = self.situer() if self.situer is not None else None
        if ou is None or ou.overall - self.traite < TRANCHE_MINIMALE_S:
            return []
        return self.transcription_turn(ou, job)

    def _is_time(self, ou: Position) -> bool:
        """Is it time to transcribe?"""
        avance = ou.overall - self.traite
        stagne = self.vu is not None and abs(ou.ecrit - self.vu) < 0.05
        self.vu = ou.ecrit
        if avance >= self.slice_period:
            return True
        return stagne and avance >= TRANCHE_MINIMALE_S
