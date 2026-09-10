#!/usr/bin/env python3
"""Rejouer le recollage des voix sur une réunion déjà enregistrée.

Le recollage décide combien de personnes le compte rendu annonce. Le régler au
jugé se paie cher : une réunion réelle de 92 minutes a rendu **298 voix pour
trois personnes autour d'une table**. Cet outil rejoue la décision sur cette
réunion-là, avec ses vraies empreintes, et la note contre les noms que
l'utilisateur a posés à la main — la seule vérité terrain dont on dispose.

    python3 outils/rejouer_recollage.py 2026-09-09_16h36_reunion

Les empreintes sont calculées une fois puis mises en cache : elles coûtent
quelques minutes, les stratégies se comparent ensuite en une seconde.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domain import voiceprints as domain  # noqa: E402
from greffier.domain.models import Span, Voiceprint  # noqa: E402
from greffier.locations import data_folder  # noqa: E402


def voiceprints_per_voice(meeting: dict, cache: Path) -> dict[str, list[Voiceprint]]:
    """Une liste d'empreintes par voix, calculée une fois et gardée."""
    if cache.exists():
        return pickle.loads(cache.read_bytes())

    import numpy as np
    import soundfile as sf

    from greffier.adapters.voiceprints_titanet import (
        DUREE_MAXIMALE,
        DUREE_MINIMALE,
        TitaNetExtractor,
    )

    model = data_folder() / "modeles/diarisation/nemo_en_titanet_large.onnx"
    extractor = TitaNetExtractor(model)

    per_voice: dict[str, list[Span]] = defaultdict(list)
    for turn in meeting["tours"]:
        per_voice[str(turn["voix"])].append(Span(turn["debut"], turn["fin"]))

    outcome: dict[str, list[Voiceprint]] = defaultdict(list)
    # Un seul parcours du fichier : `extraire_intervalles` le relit en entier à
    # chaque voix, ce qui ferait 298 lectures d'un fichier de 531 Mo.
    with sf.SoundFile(str(meeting["audio"])) as file:
        frequency = file.samplerate
        total = sum(len(v) for v in per_voice.values())
        fait = 0
        for voice, intervalles in per_voice.items():
            for span in intervalles:
                fait += 1
                if fait % 100 == 0:
                    print(f"  {fait}/{total} extraits…", file=sys.stderr)
                if span.duration < DUREE_MINIMALE:
                    continue
                start, end = span.start, span.end
                if end - start > DUREE_MAXIMALE:
                    milieu = (start + end) / 2
                    start, end = milieu - DUREE_MAXIMALE / 2, milieu + DUREE_MAXIMALE / 2
                file.seek(int(start * frequency))
                bloc = file.read(int((end - start) * frequency), dtype="float32",
                                    always_2d=True)
                if len(bloc) < DUREE_MINIMALE * frequency:
                    continue
                signal = np.ascontiguousarray(bloc.mean(axis=1))
                outcome[voice].append(extractor.extract(signal, frequency))

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(dict(outcome)))
    return dict(outcome)


def note(membership: dict[str, str], meeting: dict,
          per_voice: dict[str, list[Voiceprint]]) -> dict:
    """Ce que vaut un recollage, contre les noms posés à la main."""
    verite = {str(v): n for v, n in meeting["noms"].items()}
    duration = defaultdict(float)
    for turn in meeting["tours"]:
        voice = membership.get(str(turn["voix"]), str(turn["voix"]))
        duration[voice] += turn["fin"] - turn["debut"]

    groupes: dict[str, Counter] = defaultdict(Counter)
    for voice, name in verite.items():
        groupes[membership.get(voice, voice)][name] += sum(
            e.source_duration for e in per_voice.get(voice, [])) or 1.0

    melanges = {g: dict(c) for g, c in groupes.items() if len(c) > 1}
    eclats = Counter()
    for c in groupes.values():
        eclats[c.most_common(1)[0][0]] += 1
    total = sum(duration.values()) or 1.0
    gros = sorted(duration.items(), key=lambda x: -x[1])[:6]
    return {
        "voix": len(set(membership.values())),
        "melanges": melanges,
        "eclats": dict(eclats),
        "gros": [(g, round(s), round(100 * s / total)) for g, s in gros],
    }


def adoption(per_voice, seuil, marge, material) -> dict[str, str]:
    """Rattache les petits groupes au grand qui leur ressemble le plus.

    Le recollage par paires s'arrête dès qu'aucune paire ne franchit son seuil,
    et laisse alors des centaines de fragments isolés. La question posée ici est
    celle de la banque de voix, à l'intérieur d'une seule réunion : « lequel des
    groupes établis ressemble le plus, et **nettement** plus ». Seuil et marge,
    donc, et non un seuil seul.
    """
    membership = domain.join_voices(per_voice)
    groupes: dict[str, list[Voiceprint]] = defaultdict(list)
    for voice, vers in membership.items():
        groupes[vers].extend(per_voice.get(voice, []))
    groupes = {g: e for g, e in groupes.items() if e}
    matieres = {g: sum(x.source_duration for x in e) for g, e in groupes.items()}
    etablis = {g: domain.aggregate(e) for g, e in groupes.items() if matieres[g] >= material}
    if not etablis:
        return membership
    for petit, voiceprints in groupes.items():
        if petit in etablis:
            continue
        aggregate_of = domain.aggregate(voiceprints)
        ranking = sorted(
            ((domain.similarity(aggregate_of, a), g) for g, a in etablis.items()),
            key=lambda x: (-x[0], x[1]),
        )
        best, gagnant = ranking[0]
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if best >= seuil and best - second >= marge:
            for voice, vers in membership.items():
                if vers == petit:
                    membership[voice] = gagnant
    return membership


def consolidation(per_voice, seuil_adoption, marge, material, seuil_final) -> dict[str, str]:
    """Adoption, puis les groupes établis se comparent entre eux.

    Une fois les fragments rattachés, un groupe établi porte des minutes de
    parole et non plus quelques secondes : son agrégat cesse d'être bruité, et
    deux groupes qui sont la même personne peuvent enfin se reconnaître à un
    seuil que des fragments n'auraient pas mérité.
    """
    membership = adoption(per_voice, seuil_adoption, marge, material)
    while True:
        groupes: dict[str, list[Voiceprint]] = defaultdict(list)
        for voice, vers in membership.items():
            groupes[vers].extend(per_voice.get(voice, []))
        etablis = {g: e for g, e in groupes.items()
                   if sum(x.source_duration for x in e) >= material}
        agregats = {g: domain.aggregate(e) for g, e in etablis.items()}
        names = sorted(agregats)
        meilleure = None
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                score = domain.similarity(agregats[a], agregats[b])
                if score >= seuil_final and (meilleure is None or score > meilleure[0]):
                    meilleure = (score, a, b)
        if meilleure is None:
            return membership
        _, garde, absorbe = meilleure
        if sum(x.source_duration for x in etablis[absorbe]) > sum(
                x.source_duration for x in etablis[garde]):
            garde, absorbe = absorbe, garde
        for voice, vers in membership.items():
            if vers == absorbe:
                membership[voice] = garde


def significatives(membership, meeting, minimum=10.0) -> int:
    duration = defaultdict(float)
    for turn in meeting["tours"]:
        duration[membership.get(str(turn["voix"]), str(turn["voix"]))] += (
            turn["fin"] - turn["debut"])
    return sum(1 for d in duration.values() if d >= minimum)


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("reunion")
    arguments = parseur.parse_args()

    path = data_folder() / "reunions" / f"{arguments.meeting}.json"
    meeting = json.loads(path.read_text())
    cache = Path("/tmp/greffier-empreintes") / f"{arguments.meeting}.pickle"
    print(f"Empreintes de {arguments.meeting}…", file=sys.stderr)
    per_voice = voiceprints_per_voice(meeting, cache)
    print(f"{len(per_voice)} voix portent au moins une empreinte.\n")

    print("== recollage actuel, par seuil ==")
    for seuil in (0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45):
        note = note(domain.join_voices(per_voice, seuil=seuil), meeting, per_voice)
        print(f"seuil {seuil:.2f} → {note['voix']:4d} voix, "
              f"éclats {note['eclats']}, mélanges {len(note['melanges'])}")

    print("\n== recollage puis adoption des petits groupes ==")
    for seuil in (0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30):
        for marge in (0.0, 0.05, 0.10):
            note = note(adoption(per_voice, seuil, marge, 30.0), meeting, per_voice)
            print(f"seuil {seuil:.2f} marge {marge:.2f} → {note['voix']:4d} voix, "
                  f"éclats {note['eclats']}, mélanges {len(note['melanges'])}, "
                  f"gros {note['gros'][:4]}")
    print("\n== adoption puis consolidation des établis ==")
    for adopt in (0.45, 0.40, 0.35):
        for final in (0.70, 0.65, 0.60, 0.55, 0.50):
            a = consolidation(per_voice, adopt, 0.0, 30.0, final)
            note = note(a, meeting, per_voice)
            print(f"adoption {adopt:.2f} / consolidation {final:.2f} → "
                  f"{note['voix']:4d} voix ({significatives(a, meeting)} significatives), "
                  f"éclats {note['eclats']}, mélanges {len(note['melanges'])}, "
                  f"gros {note['gros'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
