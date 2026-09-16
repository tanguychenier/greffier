"""Finding the attendees' names in what they say.

A meeting names its own people: "thanks Tanguy", "over to you Sophie". Every
rule here exists to avoid writing an invented name into minutes, a wrong name
is worse than no name at all.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from greffier.domain.language import LanguageProfile
from greffier.domain.models import MentionKind, Span, SpeakerTurn, Utterance

WEIGHT: dict[MentionKind, int] = {
    MentionKind.AUTO_PRESENTATION: 3,
    MentionKind.ADDRESSING: 2,
    MentionKind.REFERRAL: 1,
}

FOLLOWING_WINDOW = 30.0
PREVIOUS_WINDOW = 60.0

def _without_accents(word: str) -> str:
    stripped = unicodedata.normalize("NFD", word.replace("’", "'"))
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").lower()

@dataclass(frozen=True, slots=True)
class Mention:
    """A spoken name, placed in time, and what it points at."""

    name: str
    span: Span
    type: MentionKind
    excerpt: str

    @property
    def at_instant(self) -> float:
        return self.span.start

    @property
    def key(self) -> str:
        """Normalised form, so that "Josiane" and "josiane" count together."""
        return _without_accents(self.name)

@dataclass(slots=True)
class Attribution:
    """What is believed about a voice, and on what grounds."""

    voice: str
    name: str
    score: int
    indices: list[Mention] = field(default_factory=list)
    concurrent: str | None = None      # the second best placed name, if any
    score_concurrent: int = 0

    @property
    def certain(self) -> bool:
        """Enough agreeing clues, from different origins, and no rival."""
        if self.score < 3 or self.score < 2 * self.score_concurrent:
            return False
        types = {mention.type for mention in self.indices}
        return types != {MentionKind.ADDRESSING}

@dataclass(slots=True)
class Outcome:
    certainties: dict[str, Attribution] = field(default_factory=dict)
    propositions: list[Attribution] = field(default_factory=list)

_WORD = re.compile(r"[\w'’-]+")

def _common_words(utterances: list[Utterance]) -> frozenset[str]:
    """Words the meeting also uses in lower case: never first names."""
    minuscules: set[str] = set()
    for utterance in utterances:
        for word in _WORD.findall(utterance.text):
            if word[:1].islower():
                minuscules.add(_without_accents(word))
    return frozenset(minuscules)

def spot_mentions(
    utterances: list[Utterance],
    profile: LanguageProfile,
    excluded: frozenset[str] | None = None,
) -> list[Mention]:
    """Collects every spoken name and what it points at."""
    if not profile.detection.active:
        return []
    forbidden = profile.detection.excluded | (excluded or frozenset()) | _common_words(utterances)
    francs = [(t, m) for t, m, confirmation in profile.detection.motifs if not confirmation]
    larges = [(t, m) for t, m, confirmation in profile.detection.motifs if confirmation]

    mentions = _pass(utterances, francs, forbidden, None, profile)
    known = {m.key for m in mentions}
    mentions += _pass(utterances, larges, forbidden, known, profile)
    return sorted(mentions, key=lambda m: m.at_instant)

def _pass(
    utterances: list[Utterance],
    motifs: list[tuple[MentionKind, re.Pattern[str]]],
    forbidden: frozenset[str],
    known: set[str] | None,
    profile: LanguageProfile,
) -> list[Mention]:
    mentions: list[Mention] = []
    for utterance in utterances:
        seen: dict[tuple[int, str], Mention] = {}
        for type_mention, motif in motifs:
            for found in motif.finditer(utterance.text):
                name = found.group("nom")
                if (_without_accents(name) in forbidden
                or len(name) < profile.detection.minimum_length):
                    continue
                stripped = _without_accents(name)
                the_suffix = profile.detection.adverb_suffix
                if (
                    the_suffix
                    and len(stripped) >= profile.detection.suffix_length
                    and stripped.endswith(the_suffix)
                ):
                    continue
                if known is not None and _without_accents(name) not in known:
                    continue
                position = found.start("nom")
                key = (position, _without_accents(name))
                candidate = Mention(
                    name=name,
                    span=utterance.span,
                    type=type_mention,
                    excerpt=utterance.text.strip(),
                )
                old_one = seen.get(key)
                if old_one is None or WEIGHT[type_mention] > WEIGHT[old_one.type]:
                    seen[key] = candidate
        mentions.extend(seen.values())
    return mentions

TOLERATED_GAP = 3.0

def _voice_during(span: Span, turns: list[SpeakerTurn]) -> str | None:
    """The voice that speaks the most during the utterance."""
    totals: dict[str, float] = {}
    for turn in turns:
        shared_one = span.overlap(turn.span)
        if shared_one > 0:
            totals[turn.voice] = totals.get(turn.voice, 0.0) + shared_one
    if totals:
        return max(totals, key=lambda v: totals[v])
    closest = min(
        turns,
        key=lambda t: min(abs(t.span.start - span.end),
                          abs(span.start - t.span.end)),
        default=None,
    )
    if closest is None:
        return None
    gap = min(abs(closest.span.start - span.end),
                abs(span.start - closest.span.end))
    return closest.voice if gap <= TOLERATED_GAP else None

def _next_voice(at_instant: float, current: str | None, turns: list[SpeakerTurn]) -> str | None:
    for turn in turns:
        if turn.span.start > at_instant and turn.voice != current:
            return turn.voice if turn.span.start - at_instant <= FOLLOWING_WINDOW else None
    return None

def _previous_voice(
    at_instant: float, current: str | None, turns: list[SpeakerTurn]
) -> str | None:
    the_candidate: SpeakerTurn | None = None
    for turn in turns:
        if turn.span.end <= at_instant and turn.voice != current:
            the_candidate = turn
    if the_candidate is None:
        return None
    return the_candidate.voice if at_instant - the_candidate.span.end <= PREVIOUS_WINDOW else None

def target(mention: Mention, turns: list[SpeakerTurn]) -> str | None:
    """The voice this mention points at, according to its kind."""
    current = _voice_during(mention.span, turns)
    match mention.type:
        case MentionKind.AUTO_PRESENTATION:
            return current
        case MentionKind.ADDRESSING:
            return _next_voice(mention.at_instant, current, turns)
        case MentionKind.REFERRAL:
            return _previous_voice(mention.at_instant, current, turns)

def attribute(mentions: list[Mention], turns: list[SpeakerTurn]) -> Outcome:
    """Brings spoken names and voices together, clue by clue."""
    scores: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    indices: dict[tuple[str, str], list[Mention]] = defaultdict(list)

    for mention in mentions:
        voice = target(mention, turns)
        if voice is None:
            continue
        scores[voice][mention.name] += WEIGHT[mention.type]
        indices[(voice, mention.name)].append(mention)

    candidates_: list[Attribution] = []
    for voice, by_name in scores.items():
        ranking = sorted(by_name.items(), key=lambda x: (-x[1], x[0]))
        best, score = ranking[0]
        second, score_second = ranking[1] if len(ranking) > 1 else (None, 0)
        candidates_.append(Attribution(
            voice=voice, name=best, score=score,
            indices=indices[(voice, best)],
            concurrent=second, score_concurrent=score_second,
        ))

    outcome = Outcome()
    taken: dict[str, Attribution] = {}
    for attribution in sorted(candidates_, key=lambda a: -a.score):
        if not attribution.certain:
            outcome.propositions.append(attribution)
            continue
        tenant = taken.get(_without_accents(attribution.name))
        if tenant is None:
            taken[_without_accents(attribution.name)] = attribution
            outcome.certainties[attribution.voice] = attribution
        else:
            outcome.propositions.append(attribution)

    outcome.propositions.sort(key=lambda a: -a.score)
    return outcome

def join_namesakes(
    names: dict[str, str], weight: dict[str, float]
) -> dict[str, str]:
    """Two voices given the same name are the same person.

    Measured on a real 1h42 meeting: "Lise" landed on nine separate voices, eight
    of them holding a single turn. The most fed voice wins.
    """
    carrying: dict[str, list[str]] = {}
    for voice, name in names.items():
        folded = _without_accents(name.strip().casefold())
        if folded:
            carrying.setdefault(folded, []).append(voice)
    membership = {voice: voice for voice in names}
    for group in carrying.values():
        if len(group) < 2:
            continue
        kept_one = max(group, key=lambda v: (weight.get(v, 0.0), v))
        for voice in group:
            membership[voice] = kept_one
    return membership


SHARE_TO_CARRY = 0.20
"""Share of a voice a live name must cover before it carries it.

Two cuts of the same audio never agree segment for segment: the one made while
the meeting runs and the one made afterwards split people differently, so a
name given live covers part of a voice, never all of it. Measured on a real
meeting, the shares that matter sit at 20% and above, and nothing contested
lands between.
"""

TWICE_THE_NEXT = 2.0
"""How far ahead of the next name the winner must be. Two people crossing the
same voice means the cut is wrong, and a wrong name is worse than none."""


@dataclass(frozen=True, slots=True)
class NamedSpan:
    """A stretch of the meeting a person named while it was running."""

    name: str
    span: Span


def _overlap(one: Span, other: Span) -> float:
    return max(0.0, min(one.end, other.end) - max(one.start, other.start))


def from_live(named: list[NamedSpan], turns: list[SpeakerTurn]) -> dict[str, str]:
    """The voices a human named during the meeting, carried onto this cut.

    The defect this answers: a name typed into the window while the meeting ran
    reached the voice bank and nothing else. The pass that writes the minutes
    cut the audio again, into its own voices, and named them from the bank
    alone, so the biggest speaker of a real meeting, named by hand on
    seventy-six sentences, was written up as *une voix non nommée*, while a
    person who was not in the room was announced as a participant.

    What a human said during the meeting is the strongest evidence there is.
    """
    if not named or not turns:
        return {}
    held: dict[str, float] = {}
    per_name: dict[str, dict[str, float]] = {}
    for turn in turns:
        held[turn.voice] = held.get(turn.voice, 0.0) + turn.span.duration
        for named_one in named:
            common = _overlap(turn.span, named_one.span)
            if common > 0:
                par = per_name.setdefault(turn.voice, {})
                par[named_one.name] = par.get(named_one.name, 0.0) + common
    found: dict[str, str] = {}
    for voice, shares in per_name.items():
        total = held.get(voice, 0.0)
        if total <= 0:
            continue
        sorting = sorted(shares.items(), key=lambda x: (-x[1], x[0]))
        name, best = sorting[0]
        second = sorting[1][1] if len(sorting) > 1 else 0.0
        if best / total < SHARE_TO_CARRY:
            continue
        if second > 0 and best < TWICE_THE_NEXT * second:
            continue
        found[voice] = name
    return found
