"""Recognising a voice from one meeting to the next.

A voiceprint is a vector; the whole file is cosines and thresholds, and every
threshold here was measured on real meetings rather than chosen. See
docs/calibrage.md and docs/rex-2026-09-10.md for the figures.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from greffier.domain.models import Person, Voiceprint

SEUIL_RECONNAISSANCE = 0.45
MARGE_MINIMALE = 0.06
SEUIL_CONFLIT = 0.70
SEUIL_FUSION = 0.75
EMPREINTES_PAR_PERSONNE = 8
MATIERE_MINIMALE_FUSION = 6.0
MATIERE_ETABLIE = 30.0
SEUIL_ADOPTION = 0.45
MARGE_ADOPTION = 0.0
SEUIL_CONSOLIDATION = 0.70

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
class Correspondance:
    """What the voice bank believes it recognises, and how firmly."""

    name: str
    similarity: float
    marge: float          # écart avec la deuxième personne la plus proche

    @property
    def sure(self) -> bool:
        return self.similarity >= SEUIL_RECONNAISSANCE and self.marge >= MARGE_MINIMALE

def _score(voiceprint: Voiceprint, personne: Person) -> float:
    """How close a voiceprint sits to a known person."""
    return max((similarity(voiceprint, connue) for connue in personne.voiceprints), default=-1.0)

def conflicting_names(bank: Iterable[Person]) -> dict[str, set[str]]:
    """Names in the bank that carry the same voice, pair by pair."""
    people = [p for p in bank if p.voiceprints]
    agregats = {p.name: aggregate(p.voiceprints) if len(p.voiceprints) > 1 else p.voiceprints[0]
                for p in people}
    conflits: dict[str, set[str]] = {}
    for i, un in enumerate(people):
        for autre in people[i + 1:]:
            if similarity(agregats[un.name], agregats[autre.name]) >= SEUIL_CONFLIT:
                conflits.setdefault(un.name, set()).add(autre.name)
                conflits.setdefault(autre.name, set()).add(un.name)
    return conflits

def recognise(
    voiceprint: Voiceprint,
    bank: Iterable[Person],
    seuil: float = SEUIL_RECONNAISSANCE,
    marge_minimale: float = MARGE_MINIMALE,
) -> Correspondance | None:
    """The person in the bank that matches, or nothing if doubt remains."""
    connues = [p for p in bank if p.voiceprints]
    ranking = sorted(
        ((_score(voiceprint, p), p.name) for p in connues),
        key=lambda x: (-x[0], x[1]),
    )
    if not ranking:
        return None
    best, name = ranking[0]
    second = ranking[1][0] if len(ranking) > 1 else -1.0
    marge = best - second
    if best < seuil or marge < marge_minimale:
        return None
    if name in conflicting_names(connues):
        return None
    return Correspondance(name=name, similarity=best, marge=marge)

def join_voices(
    per_voice: dict[str, list[Voiceprint]],
    seuil: float = SEUIL_FUSION,
) -> dict[str, str]:
    """Stitches back together the segment groups that are one person."""
    groupes = {voice: list(voiceprints) for voice, voiceprints in per_voice.items() if voiceprints}
    membership = {voice: voice for voice in per_voice}

    while True:
        agregats = {voice: aggregate(e) for voice, e in groupes.items()}
        names = sorted(agregats)
        meilleure: tuple[float, str, str] | None = None
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                score = similarity(agregats[a], agregats[b])
                material = max(
                    sum(e.source_duration for e in groupes[a]),
                    sum(e.source_duration for e in groupes[b]),
                )
                if (
                    score >= seuil
                    and material >= MATIERE_MINIMALE_FUSION
                    and (meilleure is None or score > meilleure[0])
                ):
                    meilleure = (score, a, b)
        if meilleure is None:
            break
        _, garde, absorbe = meilleure
        if sum(e.source_duration for e in groupes[absorbe]) > sum(
            e.source_duration for e in groupes[garde]
        ):
            garde, absorbe = absorbe, garde
        groupes[garde].extend(groupes.pop(absorbe))
        for voice, vers in membership.items():
            if vers == absorbe:
                membership[voice] = garde

    return membership

def _groupes(
    per_voice: dict[str, list[Voiceprint]], membership: dict[str, str]
) -> dict[str, list[Voiceprint]]:
    """The voiceprints gathered under the group that holds them."""
    groupes: dict[str, list[Voiceprint]] = {}
    for voice, vers in membership.items():
        voiceprints = per_voice.get(voice)
        if voiceprints:
            groupes.setdefault(vers, []).extend(voiceprints)
    return groupes

def _material(voiceprints: Iterable[Voiceprint]) -> float:
    return math.fsum(e.source_duration for e in voiceprints)

def adopt_fragments(
    per_voice: dict[str, list[Voiceprint]],
    membership: dict[str, str],
    seuil: float = SEUIL_ADOPTION,
    marge_minimale: float = MARGE_ADOPTION,
    matiere_etablie: float = MATIERE_ETABLIE,
) -> dict[str, str]:
    """Attaches each fragment to the established group it most resembles."""
    groupes = _groupes(per_voice, membership)
    etablis = {g: e for g, e in groupes.items() if _material(e) >= matiere_etablie}
    if not etablis:
        return membership

    fragments = sorted(
        (g for g in groupes if g not in etablis),
        key=lambda g: -_material(groupes[g]),
    )
    retenue = dict(membership)
    for fragment in fragments:
        aggregate_of = aggregate(groupes[fragment])
        ranking = sorted(
            ((similarity(aggregate_of, aggregate(e)), g) for g, e in etablis.items()),
            key=lambda x: (-x[0], x[1]),
        )
        best, hote = ranking[0]
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if best < seuil or best - second < marge_minimale:
            continue
        etablis[hote] = etablis[hote] + groupes[fragment]
        for voice, vers in retenue.items():
            if vers == fragment:
                retenue[voice] = hote
    return retenue

def consolidate(
    per_voice: dict[str, list[Voiceprint]],
    membership: dict[str, str],
    seuil: float = SEUIL_CONSOLIDATION,
    matiere_etablie: float = MATIERE_ETABLIE,
) -> dict[str, str]:
    """Joins two established groups that are in fact the same person."""
    retenue = dict(membership)
    while True:
        groupes = _groupes(per_voice, retenue)
        etablis = {g: e for g, e in groupes.items() if _material(e) >= matiere_etablie}
        agregats = {g: aggregate(e) for g, e in etablis.items()}
        names = sorted(agregats)
        meilleure: tuple[float, str, str] | None = None
        for i, un in enumerate(names):
            for autre in names[i + 1:]:
                score = similarity(agregats[un], agregats[autre])
                if score >= seuil and (meilleure is None or score > meilleure[0]):
                    meilleure = (score, un, autre)
        if meilleure is None:
            return retenue
        _, garde, absorbe = meilleure
        if _material(etablis[absorbe]) > _material(etablis[garde]):
            garde, absorbe = absorbe, garde
        for voice, vers in retenue.items():
            if vers == absorbe:
                retenue[voice] = garde

def stitch(
    per_voice: dict[str, list[Voiceprint]],
    seuil_paires: float = SEUIL_FUSION,
    seuil_adoption: float = SEUIL_ADOPTION,
    seuil_consolidation: float = SEUIL_CONSOLIDATION,
) -> dict[str, str]:
    """Brings the segmenter's groups down to the number of real people.

    Three passes, in this order: pairs, then adoption of the fragments, then
    consolidation of what has grown. Over-segmenting and stitching back is
    reversible; under-segmenting is not.
    """
    membership = join_voices(per_voice, seuil=seuil_paires)
    membership = adopt_fragments(per_voice, membership, seuil=seuil_adoption)
    return consolidate(per_voice, membership, seuil=seuil_consolidation)

def doubtful_entry(
    nouvelle: Voiceprint,
    vise: str,
    bank: Iterable[Person],
    marge: float = MARGE_MINIMALE,
) -> str:
    """Does this voiceprint look like it belongs to someone else?"""
    connues = {p.name: p for p in bank if p.voiceprints}
    elsewhere = [(_score(nouvelle, p), name) for name, p in connues.items() if name != vise]
    if not elsewhere:
        return ""
    best, qui = max(elsewhere)
    chez_soi = _score(nouvelle, connues[vise]) if vise in connues else -1.0
    if best < SEUIL_RECONNAISSANCE or best - chez_soi < marge:
        return ""
    if chez_soi < 0:
        return (
            f"Cette voix ressemble à {qui} ({best:.2f}), déjà en banque. "
            f"Si c'est bien {qui}, nomme-la ainsi : deux entrées pour la même "
            "personne finissent par se mettre en conflit, et alors ni l'une ni "
            "l'autre n'est reconnue."
        )
    return (
        f"Cette voix ressemble davantage à {qui} ({best:.2f}) qu'à {vise} "
        f"({chez_soi:.2f}). Si c'est une erreur, retire le nom : une empreinte "
        "fausse est reconnue à chaque réunion suivante."
    )

@dataclass(frozen=True, slots=True)
class Intruder:
    """A voiceprint that resembles someone else more than its own owner."""

    rank: int
    at_home: float
    elsewhere: float
    qui: str
    duration: float

    @property
    def gap(self) -> float:
        return self.elsewhere - self.at_home

def intruding_voiceprints(
    personne: Person,
    bank: Iterable[Person],
    ecart_minimal: float = 0.05,
) -> list[Intruder]:
    """This person's voiceprints that probably belong to another."""
    if len(personne.voiceprints) < 2:
        return []
    autres = [p for p in bank if p.name != personne.name and p.voiceprints]
    if not autres:
        return []
    suspectes = []
    for rank, voiceprint in enumerate(personne.voiceprints):
        siennes = [e for i, e in enumerate(personne.voiceprints) if i != rank]
        at_home = max(similarity(voiceprint, e) for e in siennes)
        elsewhere, qui = max((_score(voiceprint, p), p.name) for p in autres)
        if elsewhere - at_home >= ecart_minimal:
            suspectes.append(Intruder(
                rank=rank, at_home=at_home, elsewhere=elsewhere, qui=qui,
                duration=voiceprint.source_duration,
            ))
    return sorted(suspectes, key=lambda x: -x.gap)

def enrichir(
    personne: Person,
    nouvelle: Voiceprint,
    maximum: int = EMPREINTES_PAR_PERSONNE,
) -> Person:
    """Adds a voiceprint to a known person, capping how much accumulates."""
    personne.voiceprints.append(nouvelle)
    if len(personne.voiceprints) > maximum:
        personne.voiceprints.sort(key=lambda e: -e.source_duration)
        del personne.voiceprints[maximum:]
    personne.meetings += 1
    return personne
