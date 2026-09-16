"""The meeting thread, while the meeting is happening.

What the full chain does afterwards, segment, group the voices, recognise the
people, is redone here slice by slice, on far less material. Conclusions are
therefore more fragile, and that is the point of this module: **it proposes, it
does not assert**, and it keeps track of what separates a certainty from a
guess.

Three sources of knowledge, most reliable first: a human correction, the
channel (a voice arriving on the mic belongs to whoever is recording), then the
voiceprint, useful, never sure.

Nothing here knows about whisper, sherpa or a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from greffier.domain.boilerplate import is_an_annotation, is_boilerplate
from greffier.domain.channels import LOCAL_VOICE
from greffier.domain.language import LanguageProfile
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.profiles.neutral import NEUTRAL
from greffier.domain.questions import distance
from greffier.domain.voiceprints import (
    ADOPTION_THRESHOLD,
    ESTABLISHED_MATERIAL,
    aggregate,
    join_voices,
    recognise,
    similarity,
)

MINIMUM_VOICE_MATERIAL = 2.0

MATERIAL_TO_RECOGNISE = 6.0

LIVE_ADOPTION_MARGIN = 0.06

LIVE_ATTACH_THRESHOLD = 0.50

VOICES_AT_MOST = 12

LOCAL_NAME = "Toi"

UNDETERMINED_VOICE = "?"
UNDETERMINED_NAME = "Les autres"

MINIMUM_FRESH_SHARE = 0.5

LENGTH_FOR_THE_BANK_S = 3.0

MINIMUM_OVERLAP_CHARACTERS = 4

WORDS_TO_TOLERATE = 3

#: A voice earns a number of its own once it has held the floor this long.
#: Under it, unnamed, it is shown with the others rather than as a person:
#: measured on a real ninety-minute meeting, four voices held 0.7% of the words
#: between them and each took a row on screen.
#:
#: A share of the meeting was tried alongside, and removed. A share can only be
#: judged once the meeting is over, and live it never is: against the two
#: minutes elapsed so far, four seconds is a large share, so every fragment
#: earned a number on the spot and kept it. Measured over 22 meetings, 247 of
#: the 395 numbered voices were fragments of under fifteen seconds, one meeting
#: reaching "Voix 216".
CRUMB_SECONDS = 15.0

#: Under this likeness, a voiceprint resembles nobody in the room, and a
#: thread with no room left announces it with the others rather than lending
#: it a name. Measured on a ninety-minute meeting, nine people: of 646
#: voiceprints, 28 resemble the nearest established voice by less than this,
#: and the fifth centile sits at 0.257.
RESEMBLES_NOBODY = 0.25

IDENTICAL_SHARE = 0.5

_LIVE_WORD = re.compile(r"\S+")
_WORD_PUNCTUATION = ".,;:!?…\"'«»()[]-–—"

def _content_words(text: str) -> list[tuple[str, int]]:
    """The words that carry meaning, each with where it ends in the text."""
    found: list[tuple[str, int]] = []
    for word in _LIVE_WORD.finditer(text):
        nu = word.group().strip(_WORD_PUNCTUATION).casefold()
        if nu:
            found.append((nu, word.end()))
    return found

def _same_word(one: str, other: str) -> bool:
    """Two transcriptions of one word: "l'ASIS" and "Oasis"."""
    if one == other:
        return True
    shorter = min(len(one), len(other))
    if shorter < 4:
        return False
    return distance(one, other) <= (2 if shorter >= 5 else 1)

def _overlap_each_other(left: list[str], right: list[str]) -> bool:
    """True when these two word runs are the same passage, said twice."""
    if left == right:
        return True
    if len(left) < WORDS_TO_TOLERATE:
        return False
    if not all(_same_word(a, b) for a, b in zip(left, right, strict=True)):
        return False
    identical = sum(1 for a, b in zip(left, right, strict=True) if a == b)
    return identical / len(left) >= IDENTICAL_SHARE

def drop_repetition(previous: str, fresh: str) -> str:
    """Strips from the new text the tail the previous one already showed."""
    earlier = _content_words(previous)
    later = _content_words(fresh)
    if not earlier or not later:
        return fresh
    the_suffix = [word for word, _ in earlier]
    the_prefix = [word for word, _ in later]
    for length in range(min(len(the_suffix), len(the_prefix)), 0, -1):
        if not _overlap_each_other(the_suffix[-length:], the_prefix[:length]):
            continue
        if len(" ".join(the_prefix[:length])) >= MINIMUM_OVERLAP_CHARACTERS:
            return fresh[later[length - 1][1]:].lstrip(" ,.;:!?-–—")
    return fresh

READABLE_MARGIN = 0.06

class Certainty(StrEnum):
    """Where the displayed name comes from. Decides what may be done with it.

    The order matters: a source can never be overwritten by a weaker one.
    """

    HUMAN = "humaine"        # somebody corrected it by hand
    CANAL = "canal"            # the microphone says it: it is you
    RECOGNISED = "reconnue"      # la banque de voix reconnaît, marge suffisante
    PROBABLE = "probable"      # above the threshold, but little material
    UNKNOWN = "inconnue"      # aucune idée, et on le dit

    @property
    def firm(self) -> bool:
        """True once the name is no longer a guess."""
        return self in {Certainty.HUMAN, Certainty.CANAL}

_WEIGHT = {
    Certainty.HUMAN: 4,
    Certainty.CANAL: 3,
    Certainty.RECOGNISED: 2,
    Certainty.PROBABLE: 1,
    Certainty.UNKNOWN: 0,
}

@dataclass(frozen=True, slots=True)
class Block:
    """Consecutive utterances from one source.

    Attribution works on blocks rather than utterances: whisper cuts at the
    sentence, and a voiceprint taken from six words is worth nothing.
    """

    utterances: tuple[Utterance, ...]
    local: bool

    @property
    def span(self) -> Span:
        return Span(
            self.utterances[0].span.start, self.utterances[-1].span.end
        )

@dataclass(slots=True)
class LiveVoice:
    """A voice as the thread knows it at this instant."""

    identifier: str
    name: str | None = None
    certainty: Certainty = Certainty.UNKNOWN
    rank: int = 0
    voiceprints: list[Voiceprint] = field(default_factory=list)
    likeness: float = 0.0
    gap: float = 0.0

    _aggregate_of: Voiceprint | None = field(default=None, repr=False)

    def add(self, voiceprint: Voiceprint) -> None:
        """Pours in a voiceprint, and stales the aggregate."""
        self.voiceprints.append(voiceprint)
        self._aggregate_of = None

    def absorb(self, other: LiveVoice) -> None:
        """Takes over another voice's voiceprints."""
        self.voiceprints.extend(other.voiceprints)
        self._aggregate_of = None

    def forget_aggregate(self) -> None:
        """Stales the aggregate when the list changed without going through add."""
        self._aggregate_of = None

    @property
    def aggregate_of(self) -> Voiceprint:
        """The mean voiceprint of this voice, computed once per addition."""
        if self._aggregate_of is None:
            self._aggregate_of = aggregate(self.voiceprints)
        return self._aggregate_of

    @property
    def seconds(self) -> float:
        """Material gathered, to tell whether the voiceprint is worth keeping."""
        return sum(e.source_duration for e in self.voiceprints)

    @property
    def label(self) -> str:
        """What shows next to the sentence.

        The question mark is not decoration: it says the name comes from a voiceprint
        and awaits confirmation. No number yet means too little material to be
        shown as a person, so the voice is announced with the others.
        """
        if self.name is None:
            if self.identifier == UNDETERMINED_VOICE or self.rank <= 0:
                return UNDETERMINED_NAME
            return f"Voix {self.rank}"
        return self.name if self.certainty.firm else f"{self.name} ?"

    @property
    def confidence(self) -> str:
        """What the recognition is worth, in plain words. Empty when it did not play."""
        if self.name is None or not self.likeness:
            return ""
        if self.certainty is Certainty.HUMAN:
            return "nommée à la main"
        if self.certainty is Certainty.CANAL:
            return "c'est ton micro"
        digits = f"ressemblance {self.likeness:.2f}, écart {self.gap:.2f}"
        if self.certainty is Certainty.RECOGNISED:
            return f"reconnue nettement ({digits})"
        if self.gap < READABLE_MARGIN:
            return f"proche d'une autre voix, à confirmer ({digits})"
        return f"probable, peu de matière ({digits})"

    @property
    def nameable(self) -> bool:
        """False for the catch-all of scraps: it mixes several people."""
        return self.identifier != UNDETERMINED_VOICE

@dataclass(slots=True)
class LiveTurn:
    """A displayed sentence, and who the thread attributes it to."""

    number: int
    span: Span
    text: str
    voice: str

@dataclass(frozen=True, slots=True)
class Correction:
    """What a human correction changed, for the caller to act on."""

    name: str
    voice: str
    numbers: tuple[int, ...]
    voiceprint: Voiceprint | None = None
    whole_voice: bool = True

def blocks(utterances: list[Utterance], local_spans: list[Span]) -> list[Block]:
    """Groups utterances into passages from one source."""
    groups: list[Block] = []
    current: list[Utterance] = []
    local_current = False
    for utterance in sorted(utterances, key=lambda r: r.span.start):
        local = _is_local(utterance.span, local_spans)
        if current and local != local_current:
            groups.append(Block(tuple(current), local_current))
            current = []
        current.append(utterance)
        local_current = local
    if current:
        groups.append(Block(tuple(current), local_current))
    return groups

def _is_local(span: Span, local_spans: list[Span]) -> bool:
    if span.duration <= 0:
        return any(local.overlap(span) > 0 for local in local_spans)
    covered = sum(local.overlap(span) for local in local_spans)
    return covered / span.duration >= 0.5

@dataclass(frozen=True, slots=True)
class Join:
    """What has to be kept in order to undo a join of two voices.

    Joining mixes the voiceprints into one heap and deletes the absorbed voice:
    without this record the mistake is permanent.
    """

    source: str
    target: str
    voiceprints: tuple[Voiceprint, ...]
    numbers: tuple[int, ...]
    name: str | None
    certainty: Certainty
    rank: int
    likeness: float = 0.0
    gap: float = 0.0
    target_name: str | None = None
    target_certainty: Certainty = Certainty.UNKNOWN

@dataclass
class LiveThread:
    """The thread of the meeting under way: what was said, and by whom.

    One object, held by the watching process. The window only sees the log it
    publishes, and sends corrections back.
    """

    known: list[Person] = field(default_factory=list)
    join_threshold: float = LIVE_ATTACH_THRESHOLD
    people: int | None = None
    profile: LanguageProfile = NEUTRAL
    turns: list[LiveTurn] = field(default_factory=list)
    voice: dict[str, LiveVoice] = field(default_factory=dict)
    up_to: float = 0.0
    suite: int = 0
    last_rank: int = 0
    last_text: str = ""
    joins: list[Join] = field(default_factory=list)
    split_apart: set[frozenset[str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.voice.setdefault(
            LOCAL_VOICE,
            LiveVoice(LOCAL_VOICE, name=LOCAL_NAME, certainty=Certainty.CANAL),
        )
        self.voice.setdefault(UNDETERMINED_VOICE, LiveVoice(UNDETERMINED_VOICE))

    def label(self, voice: str) -> str:
        known_one = self.voice.get(voice)
        return known_one.label if known_one else f"Voix {voice}"

    def rendered(self, since: float = 0.0) -> str:
        """The thread as flowing attributed text, so that it can be questioned."""
        lines: list[str] = []
        current: str | None = None
        for turn in self.turns:
            if turn.span.end < since or not turn.text.strip():
                continue
            who = self.label(turn.voice)
            if who != current:
                lines.append(f"\n[{who}]")
                current = who
            minutes, seconds = divmod(int(turn.span.start), 60)
            lines.append(f"{minutes:02d}:{seconds:02d}  {turn.text.strip()}")
        return "\n".join(lines).strip()

    def suggestable_names(self) -> list[str]:
        """The names a correction menu can offer without inventing anything."""
        seen = [v.name for v in self.voice.values() if v.name and v.name != LOCAL_NAME]
        for person in self.known:
            if person.name not in seen:
                seen.append(person.name)
        return [LOCAL_NAME, *seen]

    def hold(self, utterances: list[Utterance]) -> list[Utterance]:
        """Discards what was already shown in the previous slice."""
        kept: list[Utterance] = []
        for utterance in utterances:
            if not utterance.text.strip():
                continue
            if is_boilerplate(utterance.text, self.profile) or is_an_annotation(
                utterance.text
            ):
                continue
            duration = utterance.span.duration
            fresh_part = utterance.span.end - max(utterance.span.start, self.up_to)
            if duration <= 0:
                if utterance.span.start >= self.up_to:
                    kept.append(utterance)
                continue
            if fresh_part / duration >= MINIMUM_FRESH_SHARE:
                kept.append(utterance)
        if kept:
            kept[0].text = drop_repetition(self.last_text, kept[0].text)
        return kept

    def attach(self, voiceprint: Voiceprint | None, local: bool) -> str:
        """The voice a block belongs to, founding one if need be."""
        if local:
            return LOCAL_VOICE
        if voiceprint is None:
            return UNDETERMINED_VOICE

        closest = self._closest_voice(voiceprint)
        if closest is None and voiceprint.source_duration < MINIMUM_VOICE_MATERIAL:
            closest = self._the_least_distant(voiceprint) or UNDETERMINED_VOICE
        if closest is None:
            closest = self._nearby_established_voice(voiceprint)
        # No room left, by the hard ceiling or by the number announced: the
        # voiceprint joins whoever it resembles most, and the catch-all when it
        # resembles nobody. Lending a name is worse than saying "les autres".
        if closest is None and (len(self._nameable_ones()) >= VOICES_AT_MOST
                               or self._in_full()):
            closest = (self._the_least_distant(voiceprint, RESEMBLES_NOBODY)
                      or UNDETERMINED_VOICE)
        if closest is not None:
            known_one = self.voice[closest]
            known_one.add(voiceprint)
            self._try_the_name_again(known_one)
            return closest

        # No number at birth: it is earned by holding a share of the meeting,
        # in `_earn_a_number`. A number handed out on the first two seconds of
        # audio fills the screen with people who never speak again.
        new_one = LiveVoice(
            identifier=self._identifier(), voiceprints=[voiceprint]
        )
        self.voice[new_one.identifier] = new_one
        self._try_the_name_again(new_one)
        return new_one.identifier

    def _nameable_ones(self) -> list[LiveVoice]:
        """The voices that name a person: neither "you" nor the catch-all."""
        return [
            voice for identifier, voice in self.voice.items()
            if identifier not in (LOCAL_VOICE, UNDETERMINED_VOICE) and voice.voiceprints
        ]

    def _in_full(self) -> bool:
        """True when as many voices exist as attendees were announced."""
        if not self.people:
            return False
        has_spoken = any(turn.voice == LOCAL_VOICE for turn in self.turns)
        remote_ones = self.people - (1 if has_spoken else 0)
        return len(self._nameable_ones()) >= max(1, remote_ones)

    def _the_least_distant(
        self, voiceprint: Voiceprint, floor: float = -1.0
    ) -> str | None:
        """The most alike voice, threshold or not. Nothing if there is none.

        `floor` is what keeps a full thread honest: pushed past the number of
        people announced, it used to lend the nearest name to a voiceprint that
        resembled it at 0.12, which is to say not at all, and two people came
        out of the meeting as one. Under the floor the answer is nothing, and
        the caller announces the voice with the others.
        """
        ranking = sorted(
            ((similarity(voiceprint, v.aggregate_of), v.identifier)
             for v in self._nameable_ones()),
            key=lambda x: (-x[0], x[1]),
        )
        if not ranking or ranking[0][0] < floor:
            return None
        return ranking[0][1]

    def _nearby_established_voice(self, voiceprint: Voiceprint) -> str | None:
        """An **already well fed** voice this voiceprint joins without hesitation.

        The threshold is not enough on its own: it also has to clearly outrun the next
        best, otherwise the scrap belongs in the catch-all.
        """
        established = [
            (similarity(voiceprint, v.aggregate_of), v.identifier)
            for v in self._nameable_ones()
            if sum(e.source_duration for e in v.voiceprints) >= ESTABLISHED_MATERIAL
        ]
        if not established:
            return None
        ranking = sorted(established, key=lambda x: (-x[0], x[1]))
        best, which_one = ranking[0]
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if best < ADOPTION_THRESHOLD or best - second < LIVE_ADOPTION_MARGIN:
            return None
        return which_one

    def _closest_voice(self, voiceprint: Voiceprint) -> str | None:
        """The voice of this meeting that most resembles, above the threshold."""
        ranking = sorted(
            (
                (similarity(voiceprint, v.aggregate_of), v.identifier)
                for v in self.voice.values()
                if v.voiceprints
            ),
            key=lambda x: (-x[0], x[1]),
        )
        if not ranking or ranking[0][0] < self.join_threshold:
            return None
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if ranking[0][0] - second < LIVE_ADOPTION_MARGIN:
            return None
        return ranking[0][1]

    def _try_the_name_again(self, voice: LiveVoice) -> None:
        """Asks the bank for a name again, now that there is more material."""
        if voice.certainty.firm or not voice.voiceprints:
            return
        if voice.seconds < MATERIAL_TO_RECOGNISE:
            return
        match = recognise(voice.aggregate_of, self.known)
        if match is None:
            return
        found_one = (
            Certainty.RECOGNISED if match.sure else Certainty.PROBABLE
        )
        if _WEIGHT[found_one] < _WEIGHT[voice.certainty]:
            return
        voice.name = match.name
        voice.certainty = found_one
        voice.likeness = match.similarity
        voice.gap = match.margin

    def _earn_a_number(self, voice: str) -> None:
        """Gives a voice its own number once it carries enough of the meeting.

        Only ever upwards: a voice shown as a person stays one, even when the
        others speak so much afterwards that its share falls back.
        """
        known_one = self.voice.get(voice)
        if known_one is None or known_one.rank > 0 or not known_one.nameable:
            return
        if voice == LOCAL_VOICE:
            return
        held = sum(t.span.duration for t in self.turns if t.voice == voice)
        if held >= CRUMB_SECONDS or self._only_voice_so_far(voice):
            known_one.rank = self._rank()

    def _only_voice_so_far(self, voice: str) -> bool:
        """Nobody else has spoken yet, so showing it as a person costs no row.

        It is what makes the opening of a meeting readable: the first speaker is
        named at once rather than announced with others who do not exist. It can
        never hand out a second number, which is what the share of the meeting
        did.
        """
        return all(t.voice == voice for t in self.turns)

    def record_turn(self, block: Block, voice: str) -> list[LiveTurn]:
        """Adds a block's sentences to the thread, attributed to a voice."""
        new_ones: list[LiveTurn] = []
        for utterance in block.utterances:
            turn = LiveTurn(
                number=len(self.turns) + 1,
                span=utterance.span,
                text=utterance.text.strip(),
                voice=voice,
            )
            self.turns.append(turn)
            new_ones.append(turn)
            self.up_to = max(self.up_to, utterance.span.end)
            if turn.text:
                self.last_text = turn.text
        self._earn_a_number(voice)
        return new_ones

    def correct(self, number: int, name: str, whole_voice: bool = True) -> Correction:
        """Imposes a name, against what the voiceprint believed.

        By default the correction covers the **whole voice**: when the tool gets the
        person wrong, it gets them wrong for every passage of that voice.
        """
        name = name.strip()
        if not name:
            raise ValueError("un nom vide ne corrige rien")
        turn = self._turn(number)
        old_one = self.voice[turn.voice]
        if whole_voice and old_one.nameable:
            return self._correct_the_voice(old_one, name)
        return self._correct_the_sentence(turn, name)

    def _correct_the_voice(self, voice: LiveVoice, name: str) -> Correction:
        fusion = self._voice_named(name)
        if fusion is not None and fusion.identifier != voice.identifier:
            self.split_apart.discard(
                frozenset({voice.identifier, fusion.identifier})
            )
            self._absorb(voice.identifier, fusion.identifier)
            voice = fusion
        voice.name = name
        voice.certainty = Certainty.HUMAN
        numbers = tuple(t.number for t in self.turns if t.voice == voice.identifier)
        return Correction(
            name=name, voice=voice.identifier, numbers=numbers,
            voiceprint=self.voiceprint_to_learn(voice), whole_voice=True,
        )

    def _absorb(self, source: str, target: str) -> None:
        """Pours one voice into another: its turns, then its voiceprints.

        Records on the way what is needed to undo it.
        """
        swallowed = self.voice[source]
        kept_one = self.voice[target]
        moved = tuple(t.number for t in self.turns if t.voice == source)
        self.joins.append(Join(
            source=source, target=target,
            voiceprints=tuple(swallowed.voiceprints), numbers=moved,
            name=swallowed.name, certainty=swallowed.certainty, rank=swallowed.rank,
            likeness=swallowed.likeness, gap=swallowed.gap,
            target_name=kept_one.name, target_certainty=kept_one.certainty,
        ))
        kept_one.absorb(swallowed)
        for turn in self.turns:
            if turn.voice == source:
                turn.voice = target
        del self.voice[source]

    def join_into(self, source: str, target: str) -> Join | None:
        """Joins two voices while keeping what it takes to undo it."""
        if source == target or source not in self.voice or target not in self.voice:
            return None
        self._absorb(source, target)
        return self.joins[-1]

    def can_split(self, target: str) -> bool:
        """True when this voice absorbed another one that can be taken back."""
        return any(
            f.target == target and f.source not in self.voice for f in self.joins
        )

    def split(self, target: str) -> Join | None:
        """Undoes the last join that produced this voice.

        The absorbed voice takes back its identifier, its voiceprints and its turns,
        and the pair is held apart from then on.
        """
        fusion = next(
            (f for f in reversed(self.joins) if f.target == target), None
        )
        if fusion is None or fusion.source in self.voice:
            return None
        kept_one = self.voice.get(target)
        if kept_one is None:
            return None
        returned = LiveVoice(
            identifier=fusion.source, name=fusion.name,
            certainty=fusion.certainty, rank=fusion.rank,
            voiceprints=list(fusion.voiceprints),
            likeness=fusion.likeness, gap=fusion.gap,
        )
        to_render = {id(e) for e in fusion.voiceprints}
        kept_one.voiceprints = [e for e in kept_one.voiceprints if id(e) not in to_render]
        kept_one.forget_aggregate()
        if kept_one.certainty is not Certainty.HUMAN:
            kept_one.name, kept_one.certainty = fusion.target_name, fusion.target_certainty
        for turn in self.turns:
            if turn.voice == target and turn.number in set(fusion.numbers):
                turn.voice = fusion.source
        self.voice[fusion.source] = returned
        self.joins.remove(fusion)
        self.split_apart.add(frozenset({fusion.source, target}))
        return fusion

    def _held_apart(self, one_of: str, other: str) -> bool:
        """True when a human already said these two voices are not the same."""
        return frozenset({one_of, other}) in self.split_apart

    def stitch(self) -> list[tuple[str, str]]:
        """Joins the voices that accumulated material shows to be one person.

        By pairs and not through the full stitching of the after-meeting chain: that
        one was measured here and dropped accuracy from 93% to 79.6%, which amounts to
        giving everything to the loudest voice.
        """
        done_ones: list[tuple[str, str]] = []
        done_ones += self.join_namesakes()
        candidates = {
            identifier: voice.voiceprints
            for identifier, voice in self.voice.items()
            if voice.voiceprints and identifier not in (LOCAL_VOICE, UNDETERMINED_VOICE)
        }
        if len(candidates) < 2:
            return done_ones
        for source, target in join_voices(candidates).items():
            if source == target or source not in self.voice or target not in self.voice:
                continue
            if self._different_human_names(source, target):
                continue
            if self._held_apart(source, target):
                continue
            self._absorb(source, target)
            done_ones.append((source, target))
        return done_ones

    def join_namesakes(self) -> list[tuple[str, str]]:
        """Two voices the bank names alike are the same person.

        The self-correction that was missing, and it costs nothing: when the bank
        answers "Tanguy" on three separate voices, it has already said those three are
        Tanguy's.
        """
        by_name: dict[str, list[LiveVoice]] = {}
        for voice in self.voice.values():
            if voice.name and voice.nameable and voice.identifier != LOCAL_VOICE:
                by_name.setdefault(voice.name.casefold(), []).append(voice)
        done_ones: list[tuple[str, str]] = []
        for carrying in by_name.values():
            if len(carrying) < 2:
                continue
            carrying.sort(key=lambda v: -v.seconds)
            kept_one = carrying[0]
            for absorbed_one in carrying[1:]:
                if self._held_apart(absorbed_one.identifier, kept_one.identifier):
                    continue
                self._absorb(absorbed_one.identifier, kept_one.identifier)
                done_ones.append((absorbed_one.identifier, kept_one.identifier))
        return done_ones

    def _different_human_names(self, one: str, other: str) -> bool:
        first, second = self.voice[one], self.voice[other]
        return (
            first.certainty is Certainty.HUMAN
            and second.certainty is Certainty.HUMAN
            and first.name != second.name
        )

    def _correct_the_sentence(self, turn: LiveTurn, name: str) -> Correction:
        """Moves a single sentence, without touching the rest of the voice."""
        target = self._voice_named(name)
        if target is None:
            target = LiveVoice(
                identifier=self._identifier(), name=name,
                certainty=Certainty.HUMAN, rank=self._rank(),
            )
            self.voice[target.identifier] = target
        turn.voice = target.identifier
        return Correction(name=name, voice=target.identifier,
                          numbers=(turn.number,), whole_voice=False)

    def voiceprint_to_learn(self, voice: LiveVoice) -> Voiceprint | None:
        """The voiceprint to pour into the bank for this voice, if there is enough.

        Nothing is poured from a voice that holds several people. What goes into
        the bank is the mean of everything the voice gathered, so a voice the cut
        got wrong pours one person's voice into another's file, and a file, once
        wrong, is wrong at every meeting that follows. Measured on a real bank:
        three entries out of five carried a stranger, and one answered to another
        person's name more readily than to its own.
        """
        from greffier.domain.voiceprints import one_person

        if voice.identifier == LOCAL_VOICE or not voice.voiceprints:
            return None
        if voice.seconds < LENGTH_FOR_THE_BANK_S:
            return None
        if not one_person(voice.voiceprints):
            return None
        return voice.aggregate_of

    def reserve_identifier(self, identifier: str) -> None:
        """Advances the counter past an identifier that came from elsewhere.

        Replaying the log without this hands out "v1" again, which overwrites the
        existing voice: two people under one identifier, with nothing to signal it.
        """
        if len(identifier) < 2 or identifier[0] != "v":
            return
        digits = identifier[1:]
        if digits.isdigit():
            self.suite = max(self.suite, int(digits))

    def _identifier(self) -> str:
        self.suite += 1
        while f"v{self.suite}" in self.voice:
            self.suite += 1
        return f"v{self.suite}"

    def _rank(self) -> int:
        """Display number of an unnamed voice: "Voix 1", "Voix 2"…

        Counted from a counter and not from the voices present: every join
        deletes one, so counting handed out a number already on screen. Three
        voices showed "Voix 11" in a ninety-minute meeting, which makes them
        impossible to tell apart and impossible to name.
        """
        self.last_rank += 1
        return self.last_rank

    def reserve_rank(self, rank: int) -> None:
        """Advances the counter past a number that came from elsewhere."""
        self.last_rank = max(self.last_rank, rank)

    def adopt_rank(self, voice: LiveVoice, rank: int) -> None:
        """Takes the number a log carries, unless another voice already shows it.

        Logs written before the counter existed carry duplicates, and replaying
        them as they are would show the same label on three voices again.
        """
        self.reserve_rank(rank)
        if voice.rank > 0:
            return  # a label already shown never changes under the reader's eyes
        if rank <= 0:
            return
        taken = any(v is not voice and v.rank == rank for v in self.voice.values())
        voice.rank = self._rank() if taken else rank

    def _voice_named(self, name: str) -> LiveVoice | None:
        folded = name.casefold()
        for voice in self.voice.values():
            if voice.name is not None and voice.name.casefold() == folded:
                return voice
        return None

    def _turn(self, number: int) -> LiveTurn:
        for turn in self.turns:
            if turn.number == number:
                return turn
        raise KeyError(f"aucune phrase numéro {number} dans le fil")
