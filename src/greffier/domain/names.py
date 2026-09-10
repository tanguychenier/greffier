"""Finding the attendees' names in what they say.

A meeting names its own people: "thanks Tanguy", "over to you Sophie". Every
rule here exists to avoid writing an invented name into minutes — a wrong name
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
FENETRE_PRECEDENT = 60.0

def _without_accents(mot: str) -> str:
    depouille = unicodedata.normalize("NFD", mot.replace("’", "'"))
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

_MOT = re.compile(r"[\w'’-]+")

def _common_words(utterances: list[Utterance]) -> frozenset[str]:
    """Words the meeting also uses in lower case: never first names."""
    minuscules: set[str] = set()
    for utterance in utterances:
        for mot in _MOT.findall(utterance.text):
            if mot[:1].islower():
                minuscules.add(_without_accents(mot))
    return frozenset(minuscules)

def spot_mentions(
    utterances: list[Utterance],
    profil: LanguageProfile,
    exclus: frozenset[str] | None = None,
) -> list[Mention]:
    """Collects every spoken name and what it points at."""
    if not profil.detection.active:
        return []
    interdits = profil.detection.exclus | (exclus or frozenset()) | _common_words(utterances)
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
        vues: dict[tuple[int, str], Mention] = {}
        for type_mention, motif in motifs:
            for trouve in motif.finditer(utterance.text):
                name = trouve.group("nom")
                if (_without_accents(name) in interdits
                or len(name) < profil.detection.longueur_minimale):
                    continue
                depouille = _without_accents(name)
                suffixe = profil.detection.suffixe_adverbial
                if (
                    suffixe
                    and len(depouille) >= profil.detection.longueur_du_suffixe
                    and depouille.endswith(suffixe)
                ):
                    continue
                if known is not None and _without_accents(name) not in known:
                    continue
                position = trouve.start("nom")
                key = (position, _without_accents(name))
                candidate = Mention(
                    name=name,
                    span=utterance.span,
                    type=type_mention,
                    extrait=utterance.text.strip(),
                )
                ancienne = vues.get(key)
                if ancienne is None or POIDS[type_mention] > POIDS[ancienne.type]:
                    vues[key] = candidate
        mentions.extend(vues.values())
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
    return candidat.voice if at_instant - candidat.span.end <= FENETRE_PRECEDENT else None

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

    Measured on a real 1h42 meeting: "Laura" landed on nine separate voices, eight
    of them holding a single turn. The most fed voice wins.
    """
    portantes: dict[str, list[str]] = {}
    for voice, name in names.items():
        replie = _without_accents(name.strip().casefold())
        if replie:
            portantes.setdefault(replie, []).append(voice)
    membership = {voice: voice for voice in names}
    for ensemble in portantes.values():
        if len(ensemble) < 2:
            continue
        gardee = max(ensemble, key=lambda v: (poids.get(v, 0.0), v))
        for voice in ensemble:
            membership[voice] = gardee
    return membership
