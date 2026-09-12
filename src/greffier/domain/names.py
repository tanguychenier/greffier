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

POIDS: dict[MentionKind, int] = {
    MentionKind.AUTO_PRESENTATION: 3,
    MentionKind.INTERPELLATION: 2,
    MentionKind.RENVOI: 1,
}

FENETRE_SUIVANT = 30.0
PREVIOUS_WINDOW = 60.0

def _without_accents(word: str) -> str:
    depouille = unicodedata.normalize("NFD", word.replace("’", "'"))
    return "".join(c for c in depouille if unicodedata.category(c) != "Mn").lower()

@dataclass(frozen=True, slots=True)
class Mention:
    """A spoken name, placed in time, and what it points at."""

    name: str
    span: Span
    type: MentionKind
    extrait: str

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
    concurrent: str | None = None      # deuxième nom le mieux placé, s'il existe
    score_concurrent: int = 0

    @property
    def certain(self) -> bool:
        """Enough agreeing clues, from different origins, and no rival."""
        if self.score < 3 or self.score < 2 * self.score_concurrent:
            return False
        types = {mention.type for mention in self.indices}
        return types != {MentionKind.INTERPELLATION}

@dataclass(slots=True)
class Outcome:
    certitudes: dict[str, Attribution] = field(default_factory=dict)
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
    profil: LanguageProfile,
    excluded: frozenset[str] | None = None,
) -> list[Mention]:
    """Collects every spoken name and what it points at."""
    if not profil.detection.active:
        return []
    interdits = profil.detection.excluded | (excluded or frozenset()) | _common_words(utterances)
    francs = [(t, m) for t, m, confirmation in profil.detection.motifs if not confirmation]
    larges = [(t, m) for t, m, confirmation in profil.detection.motifs if confirmation]

    mentions = _passe(utterances, francs, interdits, None, profil)
    known = {m.key for m in mentions}
    mentions += _passe(utterances, larges, interdits, known, profil)
    return sorted(mentions, key=lambda m: m.at_instant)

def _passe(
    utterances: list[Utterance],
    motifs: list[tuple[MentionKind, re.Pattern[str]]],
    interdits: frozenset[str],
    known: set[str] | None,
    profil: LanguageProfile,
) -> list[Mention]:
    mentions: list[Mention] = []
    for utterance in utterances:
        seen: dict[tuple[int, str], Mention] = {}
        for type_mention, motif in motifs:
            for found in motif.finditer(utterance.text):
                name = found.group("nom")
                if (_without_accents(name) in interdits
                or len(name) < profil.detection.minimum_length):
                    continue
                depouille = _without_accents(name)
                suffixe = profil.detection.adverb_suffix
                if (
                    suffixe
                    and len(depouille) >= profil.detection.suffix_length
                    and depouille.endswith(suffixe)
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
                    extrait=utterance.text.strip(),
                )
                ancienne = seen.get(key)
                if ancienne is None or POIDS[type_mention] > POIDS[ancienne.type]:
                    seen[key] = candidate
        mentions.extend(seen.values())
    return mentions

ECART_TOLERE = 3.0

def _voice_during(span: Span, turns: list[SpeakerTurn]) -> str | None:
    """The voice that speaks the most during the utterance."""
    cumuls: dict[str, float] = {}
    for turn in turns:
        commun = span.overlap(turn.span)
        if commun > 0:
            cumuls[turn.voice] = cumuls.get(turn.voice, 0.0) + commun
    if cumuls:
        return max(cumuls, key=lambda v: cumuls[v])
    proche = min(
        turns,
        key=lambda t: min(abs(t.span.start - span.end),
                          abs(span.start - t.span.end)),
        default=None,
    )
    if proche is None:
        return None
    gap = min(abs(proche.span.start - span.end),
                abs(span.start - proche.span.end))
    return proche.voice if gap <= ECART_TOLERE else None

def _next_voice(at_instant: float, courante: str | None, turns: list[SpeakerTurn]) -> str | None:
    for turn in turns:
        if turn.span.start > at_instant and turn.voice != courante:
            return turn.voice if turn.span.start - at_instant <= FENETRE_SUIVANT else None
    return None

def _previous_voice(
    at_instant: float, courante: str | None, turns: list[SpeakerTurn]
) -> str | None:
    candidat: SpeakerTurn | None = None
    for turn in turns:
        if turn.span.end <= at_instant and turn.voice != courante:
            candidat = turn
    if candidat is None:
        return None
    return candidat.voice if at_instant - candidat.span.end <= PREVIOUS_WINDOW else None

def target(mention: Mention, turns: list[SpeakerTurn]) -> str | None:
    """The voice this mention points at, according to its kind."""
    courante = _voice_during(mention.span, turns)
    match mention.type:
        case MentionKind.AUTO_PRESENTATION:
            return courante
        case MentionKind.INTERPELLATION:
            return _next_voice(mention.at_instant, courante, turns)
        case MentionKind.RENVOI:
            return _previous_voice(mention.at_instant, courante, turns)

def attribute(mentions: list[Mention], turns: list[SpeakerTurn]) -> Outcome:
    """Brings spoken names and voices together, clue by clue."""
    scores: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    indices: dict[tuple[str, str], list[Mention]] = defaultdict(list)

    for mention in mentions:
        voice = target(mention, turns)
        if voice is None:
            continue
        scores[voice][mention.name] += POIDS[mention.type]
        indices[(voice, mention.name)].append(mention)

    candidats: list[Attribution] = []
    for voice, by_name in scores.items():
        ranking = sorted(by_name.items(), key=lambda x: (-x[1], x[0]))
        best, score = ranking[0]
        second, score_second = ranking[1] if len(ranking) > 1 else (None, 0)
        candidats.append(Attribution(
            voice=voice, name=best, score=score,
            indices=indices[(voice, best)],
            concurrent=second, score_concurrent=score_second,
        ))

    outcome = Outcome()
    pris: dict[str, Attribution] = {}
    for attribution in sorted(candidats, key=lambda a: -a.score):
        if not attribution.certain:
            outcome.propositions.append(attribution)
            continue
        tenant = pris.get(_without_accents(attribution.name))
        if tenant is None:
            pris[_without_accents(attribution.name)] = attribution
            outcome.certitudes[attribution.voice] = attribution
        else:
            outcome.propositions.append(attribution)

    outcome.propositions.sort(key=lambda a: -a.score)
    return outcome

def join_namesakes(
    names: dict[str, str], poids: dict[str, float]
) -> dict[str, str]:
    """Two voices given the same name are the same person.

    Measured on a real 1h42 meeting: "Lise" landed on nine separate voices, eight
    of them holding a single turn. The most fed voice wins.
    """
    portantes: dict[str, list[str]] = {}
    for voice, name in names.items():
        replie = _without_accents(name.strip().casefold())
        if replie:
            portantes.setdefault(replie, []).append(voice)
    membership = {voice: voice for voice in names}
    for group in portantes.values():
        if len(group) < 2:
            continue
        gardee = max(group, key=lambda v: (poids.get(v, 0.0), v))
        for voice in group:
            membership[voice] = gardee
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
        for nommee in named:
            common = _overlap(turn.span, nommee.span)
            if common > 0:
                par = per_name.setdefault(turn.voice, {})
                par[nommee.name] = par.get(nommee.name, 0.0) + common
    found: dict[str, str] = {}
    for voice, shares in per_name.items():
        total = held.get(voice, 0.0)
        if total <= 0:
            continue
        classement = sorted(shares.items(), key=lambda x: (-x[1], x[0]))
        name, best = classement[0]
        second = classement[1][1] if len(classement) > 1 else 0.0
        if best / total < SHARE_TO_CARRY:
            continue
        if second > 0 and best < TWICE_THE_NEXT * second:
            continue
        found[voice] = name
    return found
