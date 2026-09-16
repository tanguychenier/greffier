"""Following the meeting while it happens, and taking corrections.

Two processes, one file. The listening one transcribes, attributes and
**appends** to the log; the window reads it as it goes and drops its
corrections in. No daemon, no network port: a file survives anything and can be
read back after a crash.

The log is append-only, corrections included: a correction does not rewrite past
lines, it publishes one saying what it changes.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from greffier.domain.boilerplate import collapse_loops
from greffier.domain.channels import subtract
from greffier.domain.live import (
    Block,
    Certainty,
    Correction,
    Join,
    LiveThread,
    LiveTurn,
    LiveVoice,
    blocks,
)
from greffier.domain.models import Person, Span, SpeakerTurn, Utterance, Voiceprint
from greffier.domain.voiceprints import aggregate
from greffier.ports import outbound

SLICE_MINIMUM_S = 3.0

KIND_TURN = "tour"
KIND_CORRECTION = "correction"
KIND_STATE = "etat"
KIND_MEETING = "reunion"
KIND_SPLIT = "separation"

@dataclass(frozen=True, slots=True)
class Position:
    """Where the recording is, according to what is actually written.

    The meeting clock will not do: it subtracts the pauses, while the file holds
    only what was captured.
    """

    chunk: Path
    written: float
    offset: float

    @property
    def overall(self) -> float:
        return self.offset + self.written

def position(
    chunks: list[Path], duration: Callable[[Path], float | None]
) -> Position | None:
    """The position in the last chunk, and the time already recorded before."""
    present_line = [m for m in chunks if duration(m) is not None]
    if not present_line:
        return None
    offset = 0.0
    for chunk in present_line[:-1]:
        offset += duration(chunk) or 0.0
    last = present_line[-1]
    return Position(chunk=last, written=duration(last) or 0.0, offset=offset)

def files(folder: Path, identifier: str) -> tuple[Path, Path]:
    """The live log and the corrections drop, for one meeting.

    Two files rather than one: neither process writes where the other writes, so
    there is no lock to take.
    """
    return (
        folder / f"{identifier}.jsonl",
        folder / f"{identifier}.corrections.jsonl",
    )

def _turn_line(turn: LiveTurn, voice: LiveVoice) -> dict[str, Any]:
    """What a sentence publishes about itself.

    The likeness and the gap behind a name from the bank travel with the
    line: a voice called « Diane ? » for a hundred seconds before being
    Alice could not be explained afterwards, the figures having stayed in
    the process. The window ignores them; the measures read them.
    """
    line = {
        "genre": KIND_TURN,
        "numero": turn.number,
        "debut": round(turn.span.start, 2),
        "fin": round(turn.span.end, 2),
        "texte": turn.text,
        "voix": turn.voice,
        "confiance": turn.confidence,
        "nom": voice.name,
        "certitude": voice.certainty.value,
        "rang": voice.rank,
    }
    if voice.name is not None and voice.likeness:
        line["ressemblance"] = round(voice.likeness, 3)
        line["ecart"] = round(voice.gap, 3)
        line["matiere"] = round(voice.seconds, 1)
    return line

def _correction_line(correction: Correction) -> dict[str, Any]:
    return {
        "genre": KIND_CORRECTION,
        "nom": correction.name,
        "voix": correction.voice,
        "numeros": list(correction.numbers),
        "toute_la_voix": correction.whole_voice,
    }

def _meeting_line(source: str, target: str) -> dict[str, Any]:
    return {"genre": KIND_MEETING, "voix": source, "vers": target}

def _split_line(fusion: Join) -> dict[str, Any]:
    """What it takes to hand a split back to the window, and to a resumed thread."""
    return {
        "genre": KIND_SPLIT,
        "voix": fusion.source,
        "de": fusion.target,
        "numeros": list(fusion.numbers),
        "nom": fusion.name,
        "certitude": fusion.certainty.value,
        "rang": fusion.rank,
        "nom_cible": fusion.target_name,
        "certitude_cible": fusion.target_certainty.value,
    }

def add(log: Path, lines: list[dict[str, Any]]) -> None:
    """Appends to the log, one line per event."""
    if not lines:
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        for line in lines:
            stream.write(json.dumps(line, ensure_ascii=False) + "\n")

def read_from(log: Path, position_octets: int = 0) -> tuple[list[dict[str, Any]], int]:
    """The lines added since the last read, and where to resume."""
    if not log.exists():
        return [], position_octets
    try:
        with log.open("rb") as stream:
            stream.seek(position_octets)
            brut = stream.read()
    except OSError:
        return [], position_octets
    if not brut:
        return [], position_octets
    complete = brut.rfind(b"\n")
    if complete < 0:
        return [], position_octets
    lines: list[dict[str, Any]] = []
    for text in brut[: complete + 1].decode("utf-8", errors="replace").splitlines():
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines, position_octets + complete + 1

def replay(lines: list[dict[str, Any]], thread: LiveThread | None = None) -> LiveThread:
    """Rebuilds the thread from the log, to display it.

    The window then works on the same objects as the listening process, so under
    the same correction rules, without ever loading a model.
    """
    thread = thread if thread is not None else LiveThread()
    for line in lines:
        kind = line.get("genre")
        if kind == KIND_TURN:
            _replay_turn(thread, line)
        elif kind == KIND_CORRECTION:
            _replay_correction(thread, line)
        elif kind == KIND_MEETING:
            _replay_join(thread, line)
        elif kind == KIND_SPLIT:
            _replay_split(thread, line)
    # A correction made in the window names a voice like another one, and the
    # join that follows belongs to the listening process. Replaying without it
    # showed the same person twice: measured on a real meeting, three people out
    # of nine, still doubled at the end of ninety minutes.
    thread.join_namesakes()
    return thread

def _replay_split(thread: LiveThread, line: dict[str, Any]) -> None:
    """Replays a split: the named turns go back to the returned voice."""
    returned, target = str(line.get("voix", "")), str(line.get("de", ""))
    if not returned or not target or returned == target:
        return
    thread.split_apart.add(frozenset({returned, target}))
    kept_one = thread.voice.get(target)
    if returned in thread.voice or kept_one is None:
        return
    numbers = {int(n) for n in line.get("numeros", [])}
    thread.reserve_identifier(returned)
    thread.reserve_rank(int(line.get("rang", 0)))
    thread.voice[returned] = LiveVoice(
        identifier=returned,
        name=line.get("nom"),
        certainty=_certitude(line.get("certitude")),
        rank=int(line.get("rang", 0)),
    )
    if kept_one.certainty is not Certainty.HUMAN:
        kept_one.name = line.get("nom_cible")
        kept_one.certainty = _certitude(line.get("certitude_cible"))
    for turn in thread.turns:
        if turn.voice == target and turn.number in numbers:
            turn.voice = returned
    thread.split_apart.add(frozenset({returned, target}))

def _certitude(value: Any) -> Certainty:
    try:
        return Certainty(str(value))
    except ValueError:
        return Certainty.UNKNOWN

def _replay_join(thread: LiveThread, line: dict[str, Any]) -> None:
    """Replays a voice join: the source's turns move to the target."""
    source, target = str(line.get("voix", "")), str(line.get("vers", ""))
    if not source or not target or source == target:
        return
    swallowed, kept_one = thread.voice.get(source), thread.voice.get(target)
    if swallowed is None or kept_one is None:
        for turn in thread.turns:
            if turn.voice == source:
                turn.voice = target
        thread.voice.pop(source, None)
        return
    closed_before = swallowed.certainty.firm
    name_before, certainty_before = swallowed.name, swallowed.certainty
    thread.join_into(source, target)
    if not kept_one.certainty.firm and closed_before:
        kept_one.name, kept_one.certainty = name_before, certainty_before

def _replay_turn(thread: LiveThread, line: dict[str, Any]) -> None:
    identifier = str(line.get("voix", ""))
    if not identifier:
        return
    thread.reserve_identifier(identifier)
    voice = thread.voice.get(identifier)
    if voice is None:
        voice = LiveVoice(identifier=identifier)
        thread.voice[identifier] = voice
    if not voice.certainty.firm:
        voice.name = line.get("nom")
        voice.certainty = Certainty(line.get("certitude", Certainty.UNKNOWN.value))
        thread.adopt_rank(voice, int(line.get("rang", 0)))
    number = int(line.get("numero", len(thread.turns) + 1))
    if any(t.number == number for t in thread.turns):
        return
    start, end = float(line.get("debut", 0.0)), float(line.get("fin", 0.0))
    confidence = line.get("confiance")
    thread.turns.append(LiveTurn(
        number=number,
        span=Span(start, max(start, end)),
        text=str(line.get("texte", "")),
        voice=identifier,
        confidence=float(confidence) if confidence is not None else None,
    ))
    thread.up_to = max(thread.up_to, end)

def _replay_correction(thread: LiveThread, line: dict[str, Any]) -> None:
    numbers = [int(n) for n in line.get("numeros", [])]
    name = str(line.get("nom", "")).strip()
    if not name or not numbers:
        return
    whole_voice = bool(line.get("toute_la_voix", len(numbers) > 1))
    known = {t.number for t in thread.turns}
    for number in numbers:
        if number in known:
            thread.correct(number, name, whole_voice=whole_voice)
            return

def request_a_split(requests: Path, voice: str) -> None:
    """Drops a split for the listening process."""
    requests.parent.mkdir(parents=True, exist_ok=True)
    with requests.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"separer": voice}, ensure_ascii=False) + "\n")

def ask(requests: Path, number: int, name: str, whole_voice: bool = True) -> None:
    """Drops a correction for the listening process."""
    requests.parent.mkdir(parents=True, exist_ok=True)
    with requests.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(
            {"numero": number, "nom": name, "toute_la_voix": whole_voice},
            ensure_ascii=False,
        ) + "\n")

@dataclass
class Follower:
    """Attributes and publishes what is said, slice after slice."""

    thread: LiveThread
    log: Path
    requests: Path
    channels: outbound.ChannelReader | None = None
    extractor: outbound.VoiceprintExtractor | None = None
    bank: outbound.VoiceBank | None = None
    segmenter: outbound.SliceSegmenter | None = None
    identifier: str = ""
    _read_ones: int = field(default=0, repr=False)
    _learned: dict[str, str] = field(default_factory=dict, repr=False)

    def take_in(
        self, slice_: Path, utterances: list[Utterance], offset: float
    ) -> list[LiveTurn]:
        """Attributes a slice's sentences and publishes them."""
        self.apply_requests()
        local_spans = self.channels.local_passages(slice_) if self.channels else []
        global_ones = [
            Span(x.start + offset, x.end + offset) for x in local_spans
        ]
        # The transcriber's repeat loop is folded here, before attribution:
        # eleven times the same sentence is one voice more and eleven lines.
        utterances = collapse_loops(utterances)
        rebased = [
            Utterance(
                span=Span(
                    r.span.start + offset, r.span.end + offset
                ),
                text=r.text, voice=r.voice, source=r.source, confidence=r.confidence,
            )
            for r in utterances
        ]
        kept = self.thread.hold(rebased)
        if not kept:
            return []

        turns = self._turns(slice_, offset)
        new_ones: list[LiveTurn] = []
        lines: list[dict[str, Any]] = []
        for block in blocks(kept, global_ones, turns):
            voiceprint = self._voiceprint(slice_, block, local_spans, offset, turns)
            voice = self.thread.attach(voiceprint, block.local)
            for turn in self.thread.record_turn(block, voice):
                new_ones.append(turn)
                lines.append(_turn_line(turn, self.thread.voice[voice]))
        for source, target in self.thread.stitch():
            lines.append(_meeting_line(source, target))
        add(self.log, lines)
        self.learn_named_voices()
        return new_ones

    def _turns(self, slice_: Path, offset: float) -> list[SpeakerTurn]:
        """The speaker turns of the slice, on the meeting clock."""
        if self.segmenter is None:
            return []
        try:
            found = self.segmenter.turns(slice_)
        except (RuntimeError, OSError, ValueError):
            return []
        return [
            SpeakerTurn(
                span=Span(turn.span.start + offset, turn.span.end + offset),
                voice=turn.voice, source=turn.source,
            )
            for turn in found
        ]

    def _voiceprint(
        self,
        slice_: Path,
        block: Block,
        local_spans: list[Span],
        offset: float,
        turns: list[SpeakerTurn] | None = None,
    ) -> Voiceprint | None:
        """The voiceprint of a remote passage, taken from what is not local.

        A block cut at the changes of speaker is read where its speaker talks,
        the interjections of the others left out, and read as one excerpt:
        the turns of a lively meeting are short, and a print asks for more
        than most of them hold.
        """
        if block.local or self.extractor is None:
            return None
        chunks = [
            piece
            for span in block.spans_of_the_speaker(turns or [])
            for piece in subtract(
                Span(max(0.0, span.start - offset), max(0.0, span.end - offset)),
                local_spans,
            )
        ]
        if not chunks:
            return None
        try:
            if block.speaker is not None:
                return self.extractor.extract_together(slice_, chunks)
            found = self.extractor.extract_spans(slice_, chunks)
        except (RuntimeError, OSError, ValueError):
            return None
        if not found:
            return None
        return found[0] if len(found) == 1 else aggregate(found)

    def apply_requests(self) -> list[Correction]:
        """Takes in what the window corrected since last time.

        Two consequences, and the second is the one that counts: the following slices
        carry the right name, and the voiceprint enters the **voice bank**.
        """
        lines, self._read_ones = read_from(self.requests, self._read_ones)
        done_ones: list[Correction] = []
        confirmations: list[dict[str, Any]] = []
        for line in lines:
            if "separer" in line:
                undone = self.thread.split(str(line["separer"]))
                if undone is not None:
                    confirmations.append(_split_line(undone))
                continue
            correction = self._apply(line)
            if correction is None:
                continue
            done_ones.append(correction)
            confirmations.append(_correction_line(correction))
        for source, target in self.thread.join_namesakes():
            confirmations.append(_meeting_line(source, target))
        add(self.log, confirmations)
        self.learn_named_voices()
        return done_ones

    def _apply(self, line: dict[str, Any]) -> Correction | None:
        try:
            return self.thread.correct(
                number=int(line["numero"]),
                name=str(line["nom"]),
                whole_voice=bool(line.get("toute_la_voix", True)),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def learn_named_voices(self) -> list[str]:
        """Pours into the bank the voices a human named, as soon as there is enough."""
        if self.bank is None:
            return []
        learned: list[str] = []
        for voice in self.thread.voice.values():
            if voice.certainty is not Certainty.HUMAN or voice.name is None:
                continue
            if self._learned.get(voice.identifier) == voice.name:
                continue
            voiceprint = self.thread.voiceprint_to_learn(voice)
            if voiceprint is None:
                continue
            with contextlib.suppress(OSError):
                self.bank.record(
                    voice.name, replace(voiceprint, origin=self.identifier))
                self._learned[voice.identifier] = voice.name
                learned.append(voice.name)
        return learned

    def announce(self, message: str, active: bool = True) -> None:
        """Tells the window what the live thread can do, or why it cannot."""
        add(self.log, [{"genre": KIND_STATE, "message": message, "actif": active}])

def known_people(bank: outbound.VoiceBank | None) -> list[Person]:
    """The voice bank, or nothing when it cannot be read."""
    if bank is None:
        return []
    try:
        return bank.people()
    except OSError:
        return []
