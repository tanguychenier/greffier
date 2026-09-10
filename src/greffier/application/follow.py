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
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.voiceprints import aggregate
from greffier.ports import outbound

TRANCHE_MINIMALE_S = 3.0

GENRE_TOUR = "tour"
GENRE_CORRECTION = "correction"
GENRE_ETAT = "etat"
GENRE_REUNION = "reunion"
GENRE_SEPARATION = "separation"

@dataclass(frozen=True, slots=True)
class Position:
    """Where the recording is, according to what is actually written.

    The meeting clock will not do: it subtracts the pauses, while the file holds
    only what was captured.
    """

    morceau: Path
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
    for morceau in present_line[:-1]:
        offset += duration(morceau) or 0.0
    dernier = present_line[-1]
    return Position(morceau=dernier, written=duration(dernier) or 0.0, offset=offset)

def files(folder: Path, identifier: str) -> tuple[Path, Path]:
    """The live log and the corrections drop, for one meeting.

    Two files rather than one: neither process writes where the other writes, so
    there is no lock to take.
    """
    return (
        folder / f"{identifier}.jsonl",
        folder / f"{identifier}.corrections.jsonl",
    )

def _ligne_tour(turn: LiveTurn, voice: LiveVoice) -> dict[str, Any]:
    """What a sentence publishes about itself."""
    return {
        "genre": GENRE_TOUR,
        "numero": turn.number,
        "debut": round(turn.span.start, 2),
        "fin": round(turn.span.end, 2),
        "texte": turn.text,
        "voix": turn.voice,
        "nom": voice.name,
        "certitude": voice.certainty.value,
        "rang": voice.rank,
    }

def _ligne_correction(correction: Correction) -> dict[str, Any]:
    return {
        "genre": GENRE_CORRECTION,
        "nom": correction.name,
        "voix": correction.voice,
        "numeros": list(correction.numbers),
        "toute_la_voix": correction.whole_voice,
    }

def _ligne_reunion(source: str, target: str) -> dict[str, Any]:
    return {"genre": GENRE_REUNION, "voix": source, "vers": target}

def _ligne_separation(fusion: Join) -> dict[str, Any]:
    """What it takes to hand a split back to the window, and to a resumed thread."""
    return {
        "genre": GENRE_SEPARATION,
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
    complet = brut.rfind(b"\n")
    if complet < 0:
        return [], position_octets
    lines: list[dict[str, Any]] = []
    for text in brut[: complet + 1].decode("utf-8", errors="replace").splitlines():
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines, position_octets + complet + 1

def replay(lines: list[dict[str, Any]], thread: LiveThread | None = None) -> LiveThread:
    """Rebuilds the thread from the log, to display it.

    The window then works on the same objects as the listening process, so under
    the same correction rules — without ever loading a model.
    """
    thread = thread if thread is not None else LiveThread()
    for line in lines:
        kind = line.get("genre")
        if kind == GENRE_TOUR:
            _replay_turn(thread, line)
        elif kind == GENRE_CORRECTION:
            _replay_correction(thread, line)
        elif kind == GENRE_REUNION:
            _replay_join(thread, line)
        elif kind == GENRE_SEPARATION:
            _replay_split(thread, line)
    return thread

def _replay_split(thread: LiveThread, line: dict[str, Any]) -> None:
    """Replays a split: the named turns go back to the returned voice."""
    rendue, target = str(line.get("voix", "")), str(line.get("de", ""))
    if not rendue or not target or rendue == target:
        return
    thread.split_apart.add(frozenset({rendue, target}))
    gardee = thread.voice.get(target)
    if rendue in thread.voice or gardee is None:
        return
    numbers = {int(n) for n in line.get("numeros", [])}
    thread.reserve_identifier(rendue)
    thread.voice[rendue] = LiveVoice(
        identifier=rendue,
        name=line.get("nom"),
        certainty=_certitude(line.get("certitude")),
        rank=int(line.get("rang", 0)),
    )
    if gardee.certainty is not Certainty.HUMAINE:
        gardee.name = line.get("nom_cible")
        gardee.certainty = _certitude(line.get("certitude_cible"))
    for turn in thread.turns:
        if turn.voice == target and turn.number in numbers:
            turn.voice = rendue
    thread.split_apart.add(frozenset({rendue, target}))

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
    avalee, gardee = thread.voice.get(source), thread.voice.get(target)
    if avalee is None or gardee is None:
        for turn in thread.turns:
            if turn.voice == source:
                turn.voice = target
        thread.voice.pop(source, None)
        return
    ferme_avant = avalee.certainty.firm
    nom_avant, certitude_avant = avalee.name, avalee.certainty
    thread.join_into(source, target)
    if not gardee.certainty.firm and ferme_avant:
        gardee.name, gardee.certainty = nom_avant, certitude_avant

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
        voice.rank = int(line.get("rang", 0))
    number = int(line.get("numero", len(thread.turns) + 1))
    if any(t.number == number for t in thread.turns):
        return
    start, end = float(line.get("debut", 0.0)), float(line.get("fin", 0.0))
    thread.turns.append(LiveTurn(
        number=number,
        span=Span(start, max(start, end)),
        text=str(line.get("texte", "")),
        voice=identifier,
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
    identifier: str = ""
    _lues: int = field(default=0, repr=False)
    _appris: dict[str, str] = field(default_factory=dict, repr=False)

    def take_in(
        self, slice_: Path, utterances: list[Utterance], offset: float
    ) -> list[LiveTurn]:
        """Attributes a slice's sentences and publishes them."""
        self.apply_requests()
        local_spans = self.channels.local_passages(slice_) if self.channels else []
        globaux = [
            Span(x.start + offset, x.end + offset) for x in local_spans
        ]
        # La boucle de répétition du transcripteur se coupe ici, avant
        # l'attribution : onze fois la même phrase, c'est une voix de plus et
        # onze lignes dans le fil.
        utterances = collapse_loops(utterances)
        recalees = [
            Utterance(
                span=Span(
                    r.span.start + offset, r.span.end + offset
                ),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in utterances
        ]
        kept = self.thread.hold(recalees)
        if not kept:
            return []

        nouveaux: list[LiveTurn] = []
        lines: list[dict[str, Any]] = []
        for block in blocks(kept, globaux):
            voiceprint = self._voiceprint(slice_, block, local_spans, offset)
            voice = self.thread.attach(voiceprint, block.local)
            for turn in self.thread.record_turn(block, voice):
                nouveaux.append(turn)
                lines.append(_ligne_tour(turn, self.thread.voice[voice]))
        for source, target in self.thread.stitch():
            lines.append(_ligne_reunion(source, target))
        add(self.log, lines)
        self.learn_named_voices()
        return nouveaux

    def _voiceprint(
        self, slice_: Path, block: Block, local_spans: list[Span], offset: float
    ) -> Voiceprint | None:
        """The voiceprint of a remote passage, taken from what is not local."""
        if block.local or self.extractor is None:
            return None
        within_the_slice = Span(
            max(0.0, block.span.start - offset),
            max(0.0, block.span.end - offset),
        )
        chunks = subtract(within_the_slice, local_spans)
        if not chunks:
            return None
        try:
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
        lines, self._lues = read_from(self.requests, self._lues)
        faites: list[Correction] = []
        confirmations: list[dict[str, Any]] = []
        for line in lines:
            if "separer" in line:
                defaite = self.thread.split(str(line["separer"]))
                if defaite is not None:
                    confirmations.append(_ligne_separation(defaite))
                continue
            correction = self._appliquer(line)
            if correction is None:
                continue
            faites.append(correction)
            confirmations.append(_ligne_correction(correction))
        add(self.log, confirmations)
        self.learn_named_voices()
        return faites

    def _appliquer(self, line: dict[str, Any]) -> Correction | None:
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
        appris: list[str] = []
        for voice in self.thread.voice.values():
            if voice.certainty is not Certainty.HUMAINE or voice.name is None:
                continue
            if self._appris.get(voice.identifier) == voice.name:
                continue
            voiceprint = self.thread.voiceprint_to_learn(voice)
            if voiceprint is None:
                continue
            with contextlib.suppress(OSError):
                self.bank.record(
                    voice.name, replace(voiceprint, origin=self.identifier))
                self._appris[voice.identifier] = voice.name
                appris.append(voice.name)
        return appris

    def annoncer(self, message: str, active: bool = True) -> None:
        """Tells the window what the live thread can do, or why it cannot."""
        add(self.log, [{"genre": GENRE_ETAT, "message": message, "actif": active}])

def known_people(bank: outbound.VoiceBank | None) -> list[Person]:
    """The voice bank, or nothing when it cannot be read."""
    if bank is None:
        return []
    try:
        return bank.people()
    except OSError:
        return []
