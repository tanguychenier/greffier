"""Recognising a voice from one meeting to the next.

A voiceprint is a vector; the whole file is cosines and thresholds, and every
threshold here was measured on real meetings rather than chosen. See
docs/calibrage.md and docs/rex-2026-09-10.md for the figures.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from greffier.domain.models import Person, Voiceprint

RECOGNITION_THRESHOLD = 0.45
MINIMUM_MARGIN = 0.06
CONFLICT_THRESHOLD = 0.70
JOIN_THRESHOLD = 0.75
VOICEPRINTS_PER_PERSON = 8
MINIMUM_JOIN_MATERIAL = 6.0
ESTABLISHED_MATERIAL = 30.0
ADOPTION_THRESHOLD = 0.45
ADOPTION_MARGIN = 0.0
CONSOLIDATION_THRESHOLD = 0.70

COMMON_LEVEL = 0.06

SILENCE_FLOOR = 1e-4

def at_a_common_level(samples: Sequence[float]) -> list[float]:
    """Brings an excerpt to one loudness before it is turned into a voiceprint.

    The model is not level-invariant. Measured on a single excerpt compared
    against itself, attenuated: 0.999 at -3 dB, 0.982 at -12 dB, 0.948 at
    -18 dB, **0.874 at -24 dB**. The thresholds that decide whether two
    excerpts are one person sit between 0.45 and 0.75, so a tenth of
    similarity lost to level alone is enough to split one person into two
    voices -- which is what a meeting does to somebody who leans back, turns
    their head, or joins from a room where the microphone is further away.

    A quiet excerpt is left alone rather than amplified: multiplying silence
    by a hundred turns room noise into a voice. And the gain never pushes the
    loudest sample past full scale: clipping moves the timbre further than the
    level ever did.
    """
    carre = math.fsum(float(x) * float(x) for x in samples)
    if not samples or carre <= 0:
        return [float(x) for x in samples]
    rms = math.sqrt(carre / len(samples))
    if rms < SILENCE_FLOOR:
        return [float(x) for x in samples]
    facteur = COMMON_LEVEL / rms
    plus_haut = max(abs(float(x)) for x in samples)
    if plus_haut * facteur > 0.99:
        facteur = 0.99 / plus_haut
    return [float(x) * facteur for x in samples]

def normalise(vector: Sequence[float], source_duration: float = 0.0) -> Voiceprint:
    """Brings the vector to length 1, so that a cosine is a dot product."""
    norme = math.sqrt(math.fsum(x * x for x in vector))
    if norme == 0:
        raise ValueError("vecteur nul : extrait sans parole ?")
    return Voiceprint(vector=tuple(x / norme for x in vector), source_duration=source_duration)

def similarity(a: Voiceprint, b: Voiceprint) -> float:
    """Cosine between two normalised voiceprints, in [-1, 1]."""
    if len(a.vector) != len(b.vector):
        raise ValueError(
            f"empreintes de tailles différentes : {len(a.vector)} et {len(b.vector)}"
        )
    return math.fsum(x * y for x, y in zip(a.vector, b.vector, strict=True))

def aggregate(voiceprints: Iterable[Voiceprint]) -> Voiceprint:
    """Mean voiceprint of one voice, weighted by how long each excerpt lasted."""
    listing = list(voiceprints)
    if not listing:
        raise ValueError("aucune empreinte à agréger")
    taille = len(listing[0].vector)
    poids_total = math.fsum(max(e.source_duration, 1e-6) for e in listing)
    somme = [
        math.fsum(e.vector[i] * max(e.source_duration, 1e-6) for e in listing) / poids_total
        for i in range(taille)
    ]
    return normalise(somme, source_duration=math.fsum(e.source_duration for e in listing))

@dataclass(frozen=True, slots=True)
class Match:
    """What the voice bank believes it recognises, and how firmly."""

    name: str
    similarity: float
    margin: float          # écart avec la deuxième personne la plus proche

    @property
    def sure(self) -> bool:
        return self.similarity >= RECOGNITION_THRESHOLD and self.margin >= MINIMUM_MARGIN

def _score(voiceprint: Voiceprint, person: Person) -> float:
    """How close a voiceprint sits to a known person."""
    return max((similarity(voiceprint, connue) for connue in person.voiceprints), default=-1.0)

def conflicting_names(bank: Iterable[Person]) -> dict[str, set[str]]:
    """Names in the bank that carry the same voice, pair by pair."""
    people = [p for p in bank if p.voiceprints]
    agregats = {p.name: aggregate(p.voiceprints) if len(p.voiceprints) > 1 else p.voiceprints[0]
                for p in people}
    conflicts: dict[str, set[str]] = {}
    for i, one in enumerate(people):
        for other in people[i + 1:]:
            if similarity(agregats[one.name], agregats[other.name]) >= CONFLICT_THRESHOLD:
                conflicts.setdefault(one.name, set()).add(other.name)
                conflicts.setdefault(other.name, set()).add(one.name)
    return conflicts

def recognise(
    voiceprint: Voiceprint,
    bank: Iterable[Person],
    threshold: float = RECOGNITION_THRESHOLD,
    minimum_margin: float = MINIMUM_MARGIN,
) -> Match | None:
    """The person in the bank that matches, or nothing if doubt remains."""
    known = [p for p in bank if p.voiceprints]
    ranking = sorted(
        ((_score(voiceprint, p), p.name) for p in known),
        key=lambda x: (-x[0], x[1]),
    )
    if not ranking:
        return None
    best, name = ranking[0]
    second = ranking[1][0] if len(ranking) > 1 else -1.0
    margin = best - second
    if best < threshold or margin < minimum_margin:
        return None
    if name in conflicting_names(known):
        return None
    return Match(name=name, similarity=best, margin=margin)

def join_voices(
    per_voice: dict[str, list[Voiceprint]],
    threshold: float = JOIN_THRESHOLD,
) -> dict[str, str]:
    """Stitches back together the segment groups that are one person."""
    groups = {voice: list(voiceprints) for voice, voiceprints in per_voice.items() if voiceprints}
    membership = {voice: voice for voice in per_voice}

    while True:
        agregats = {voice: aggregate(e) for voice, e in groups.items()}
        names = sorted(agregats)
        best: tuple[float, str, str] | None = None
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                score = similarity(agregats[a], agregats[b])
                material = max(
                    sum(e.source_duration for e in groups[a]),
                    sum(e.source_duration for e in groups[b]),
                )
                if (
                    score >= threshold
                    and material >= MINIMUM_JOIN_MATERIAL
                    and (best is None or score > best[0])
                ):
                    best = (score, a, b)
        if best is None:
            break
        _, garde, absorbe = best
        if sum(e.source_duration for e in groups[absorbe]) > sum(
            e.source_duration for e in groups[garde]
        ):
            garde, absorbe = absorbe, garde
        groups[garde].extend(groups.pop(absorbe))
        for voice, into in membership.items():
            if into == absorbe:
                membership[voice] = garde

    return membership

def _groups(
    per_voice: dict[str, list[Voiceprint]], membership: dict[str, str]
) -> dict[str, list[Voiceprint]]:
    """The voiceprints gathered under the group that holds them."""
    groups: dict[str, list[Voiceprint]] = {}
    for voice, into in membership.items():
        voiceprints = per_voice.get(voice)
        if voiceprints:
            groups.setdefault(into, []).extend(voiceprints)
    return groups

def _material(voiceprints: Iterable[Voiceprint]) -> float:
    return math.fsum(e.source_duration for e in voiceprints)

def adopt_fragments(
    per_voice: dict[str, list[Voiceprint]],
    membership: dict[str, str],
    threshold: float = ADOPTION_THRESHOLD,
    minimum_margin: float = ADOPTION_MARGIN,
    matiere_etablie: float = ESTABLISHED_MATERIAL,
) -> dict[str, str]:
    """Attaches each fragment to the established group it most resembles."""
    groups = _groups(per_voice, membership)
    etablis = {g: e for g, e in groups.items() if _material(e) >= matiere_etablie}
    if not etablis:
        return membership

    fragments = sorted(
        (g for g in groups if g not in etablis),
        key=lambda g: -_material(groups[g]),
    )
    retenue = dict(membership)
    for fragment in fragments:
        aggregate_of = aggregate(groups[fragment])
        ranking = sorted(
            ((similarity(aggregate_of, aggregate(e)), g) for g, e in etablis.items()),
            key=lambda x: (-x[0], x[1]),
        )
        best, hote = ranking[0]
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if best < threshold or best - second < minimum_margin:
            continue
        etablis[hote] = etablis[hote] + groups[fragment]
        for voice, into in retenue.items():
            if into == fragment:
                retenue[voice] = hote
    return retenue

def consolidate(
    per_voice: dict[str, list[Voiceprint]],
    membership: dict[str, str],
    threshold: float = CONSOLIDATION_THRESHOLD,
    matiere_etablie: float = ESTABLISHED_MATERIAL,
) -> dict[str, str]:
    """Joins two established groups that are in fact the same person."""
    retenue = dict(membership)
    while True:
        groups = _groups(per_voice, retenue)
        etablis = {g: e for g, e in groups.items() if _material(e) >= matiere_etablie}
        agregats = {g: aggregate(e) for g, e in etablis.items()}
        names = sorted(agregats)
        best: tuple[float, str, str] | None = None
        for i, one in enumerate(names):
            for other in names[i + 1:]:
                score = similarity(agregats[one], agregats[other])
                if score >= threshold and (best is None or score > best[0]):
                    best = (score, one, other)
        if best is None:
            return retenue
        _, garde, absorbe = best
        if _material(etablis[absorbe]) > _material(etablis[garde]):
            garde, absorbe = absorbe, garde
        for voice, into in retenue.items():
            if into == absorbe:
                retenue[voice] = garde

def stitch(
    per_voice: dict[str, list[Voiceprint]],
    seuil_paires: float = JOIN_THRESHOLD,
    seuil_adoption: float = ADOPTION_THRESHOLD,
    seuil_consolidation: float = CONSOLIDATION_THRESHOLD,
) -> dict[str, str]:
    """Brings the segmenter's groups down to the number of real people.

    Three passes, in this order: pairs, then adoption of the fragments, then
    consolidation of what has grown. Over-segmenting and stitching back is
    reversible; under-segmenting is not.
    """
    membership = join_voices(per_voice, threshold=seuil_paires)
    membership = adopt_fragments(per_voice, membership, threshold=seuil_adoption)
    return consolidate(per_voice, membership, threshold=seuil_consolidation)

def one_person(
    voiceprints: Sequence[Voiceprint],
    threshold: float = JOIN_THRESHOLD,
) -> bool:
    """Do these voiceprints hold one person, or several?

    The same number that decides two voices are one person, turned on a single
    voice: if its own voiceprints do not reach it with each other, it is not one
    voice.

    Measured on the bank of a real team, the separation is not close. The clean
    entries sit at 0.87 and 0.81 between their own voiceprints; the entries fed
    from a live voice that held two people sit at 0.43, 0.53 and 0.53, and one
    of them answers to another person's name at 0.71, higher than to its own.
    """
    if len(voiceprints) < 2:
        return True
    return all(
        similarity(one, other) >= threshold
        for one, other in itertools.combinations(voiceprints, 2)
    )


def doubtful_entry(
    nouvelle: Voiceprint,
    vise: str,
    bank: Iterable[Person],
    margin: float = MINIMUM_MARGIN,
) -> str:
    """Does this voiceprint look like it belongs to someone else?"""
    known = {p.name: p for p in bank if p.voiceprints}
    elsewhere = [(_score(nouvelle, p), name) for name, p in known.items() if name != vise]
    if not elsewhere:
        return ""
    best, who = max(elsewhere)
    chez_soi = _score(nouvelle, known[vise]) if vise in known else -1.0
    if best < RECOGNITION_THRESHOLD or best - chez_soi < margin:
        return ""
    if chez_soi < 0:
        return (
            f"Cette voix ressemble à {who} ({best:.2f}), déjà en banque. "
            f"Si c'est bien {who}, nomme-la ainsi : deux entrées pour la même "
            "personne finissent par se mettre en conflit, et alors ni l'une ni "
            "l'autre n'est reconnue."
        )
    return (
        f"Cette voix ressemble davantage à {who} ({best:.2f}) qu'à {vise} "
        f"({chez_soi:.2f}). Si c'est une erreur, retire le nom : une empreinte "
        "fausse est reconnue à chaque réunion suivante."
    )

@dataclass(frozen=True, slots=True)
class Intruder:
    """A voiceprint that resembles someone else more than its own owner."""

    rank: int
    at_home: float
    elsewhere: float
    who: str
    duration: float

    @property
    def gap(self) -> float:
        return self.elsewhere - self.at_home

def intruding_voiceprints(
    person: Person,
    bank: Iterable[Person],
    ecart_minimal: float = 0.05,
) -> list[Intruder]:
    """This person's voiceprints that probably belong to another."""
    if len(person.voiceprints) < 2:
        return []
    others = [p for p in bank if p.name != person.name and p.voiceprints]
    if not others:
        return []
    suspectes = []
    for rank, voiceprint in enumerate(person.voiceprints):
        siennes = [e for i, e in enumerate(person.voiceprints) if i != rank]
        at_home = max(similarity(voiceprint, e) for e in siennes)
        elsewhere, who = max((_score(voiceprint, p), p.name) for p in others)
        if elsewhere - at_home >= ecart_minimal:
            suspectes.append(Intruder(
                rank=rank, at_home=at_home, elsewhere=elsewhere, who=who,
                duration=voiceprint.source_duration,
            ))
    return sorted(suspectes, key=lambda x: -x.gap)

def enrichir(
    person: Person,
    nouvelle: Voiceprint,
    maximum: int = VOICEPRINTS_PER_PERSON,
) -> Person:
    """Adds a voiceprint to a known person, capping how much accumulates."""
    person.voiceprints.append(nouvelle)
    if len(person.voiceprints) > maximum:
        person.voiceprints.sort(key=lambda e: -e.source_duration)
        del person.voiceprints[maximum:]
    person.meetings += 1
    return person
