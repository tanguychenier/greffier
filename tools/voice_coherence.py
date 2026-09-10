#!/usr/bin/env python3
"""Une grosse voix est-elle une seule personne ?

La question s'est posée sur une réunion réelle où « Pascal » portait 58 minutes
sur 91, soit 64,5 % de la parole. On ne peut pas y répondre en regardant les
noms : les participants non nommés qu'une grosse voix aurait absorbés ne se
voient nulle part. On y répond en regardant **la forme du nuage**.

La cohérence interne d'une voix est la ressemblance de chacun de ses extraits à
son propre agrégat. Une voix qui mélange deux personnes a une cohérence **plus
basse** que les autres : son agrégat tombe entre deux nuages, donc il est loin
des deux. C'est un signe négatif utilisable sans vérité terrain.

    python3 tools/voice_coherence.py 2026-09-10_10h10_reunion

Les empreintes viennent du cache de « replay_stitching.py » : lance-le d'abord.
"""

from __future__ import annotations

import argparse
import pickle
import statistics as stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domain.models import Voiceprint  # noqa: E402
from greffier.domain.voiceprints import aggregate, similarity  # noqa: E402

#: En deçà, un extrait ne ressemble plus à sa propre voix.
ETRANGER = 0.50

#: Sous ce nombre d'extraits, une médiane ne veut rien dire.
ASSEZ_D_EXTRAITS = 12


def cache_de(meeting: str) -> Path:
    return Path("/tmp/greffier-empreintes") / f"{meeting}.pickle"


def coherence(voiceprints: list[Voiceprint]) -> list[float]:
    """Ressemblance de chaque extrait à l'agrégat de sa propre voix."""
    ag = aggregate(voiceprints)
    return sorted(similarity(e, ag) for e in voiceprints)


def main() -> int:
    analyse = argparse.ArgumentParser(description=__doc__)
    analyse.add_argument("reunion")
    analyse.add_argument("--combien", type=int, default=6,
                         help="Combien de voix examiner (les plus grosses)")
    arguments = analyse.parse_args()

    cache = cache_de(arguments.meeting)
    if not cache.exists():
        print("Les empreintes manquent : lance d'abord "
              "« tools/replay_stitching.py » sur cette réunion.", file=sys.stderr)
        return 1
    per_voice: dict[str, list[Voiceprint]] = pickle.loads(cache.read_bytes())
    grosses = sorted(
        per_voice.items(), key=lambda kv: -sum(e.source_duration for e in kv[1])
    )[: arguments.how_many]

    print("== cohérence interne : chaque extrait contre l'agrégat de sa voix ==")
    print(f"{'voix':>6} {'extraits':>9} {'secondes':>9} "
          f"{'médiane':>9} {'1er déc.':>9} {'min':>7}  étrangers")
    for voice, voiceprints in grosses:
        seconds = sum(e.source_duration for e in voiceprints)
        if len(voiceprints) < ASSEZ_D_EXTRAITS:
            print(f"{voice:>6} {len(voiceprints):>9} {seconds:>9.0f}"
                  f"   trop peu d'extraits pour conclure")
            continue
        values = coherence(voiceprints)
        etrangers = sum(1 for v in values if v < ETRANGER)
        print(f"{voice:>6} {len(voiceprints):>9} {seconds:>9.0f} "
              f"{stat.median(values):>9.3f} {values[len(values) // 10]:>9.3f} "
              f"{values[0]:>7.3f}  {etrangers:>4} / {len(values)}")

    print("\n== repère : les grosses voix entre elles ==")
    agregats = {v: aggregate(e) for v, e in grosses}
    identifiers = [v for v, _ in grosses]
    for i, one in enumerate(identifiers):
        for other in identifiers[i + 1:]:
            print(f"  {one:>6} ↔ {other:<6} {similarity(agregats[one], agregats[other]):.3f}")

    print("\nUne voix moins cohérente que ses voisines mélange probablement deux")
    print("personnes. Plus cohérente qu'elles, c'est une seule personne bavarde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
