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

    python3 outils/coherence_des_voix.py 2026-09-10_10h10_reunion

Les empreintes viennent du cache de « rejouer_recollage.py » : lance-le d'abord.
"""

from __future__ import annotations

import argparse
import pickle
import statistics as stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domaine.empreintes import agreger, similarite  # noqa: E402
from greffier.domaine.modeles import Empreinte  # noqa: E402

#: En deçà, un extrait ne ressemble plus à sa propre voix.
ETRANGER = 0.50

#: Sous ce nombre d'extraits, une médiane ne veut rien dire.
ASSEZ_D_EXTRAITS = 12


def cache_de(reunion: str) -> Path:
    return Path("/tmp/greffier-empreintes") / f"{reunion}.pickle"


def coherence(empreintes: list[Empreinte]) -> list[float]:
    """Ressemblance de chaque extrait à l'agrégat de sa propre voix."""
    ag = agreger(empreintes)
    return sorted(similarite(e, ag) for e in empreintes)


def main() -> int:
    analyse = argparse.ArgumentParser(description=__doc__)
    analyse.add_argument("reunion")
    analyse.add_argument("--combien", type=int, default=6,
                         help="Combien de voix examiner (les plus grosses)")
    arguments = analyse.parse_args()

    cache = cache_de(arguments.reunion)
    if not cache.exists():
        print("Les empreintes manquent : lance d'abord "
              "« outils/rejouer_recollage.py » sur cette réunion.", file=sys.stderr)
        return 1
    par_voix: dict[str, list[Empreinte]] = pickle.loads(cache.read_bytes())
    grosses = sorted(
        par_voix.items(), key=lambda kv: -sum(e.duree_source for e in kv[1])
    )[: arguments.combien]

    print("== cohérence interne : chaque extrait contre l'agrégat de sa voix ==")
    print(f"{'voix':>6} {'extraits':>9} {'secondes':>9} "
          f"{'médiane':>9} {'1er déc.':>9} {'min':>7}  étrangers")
    for voix, empreintes in grosses:
        secondes = sum(e.duree_source for e in empreintes)
        if len(empreintes) < ASSEZ_D_EXTRAITS:
            print(f"{voix:>6} {len(empreintes):>9} {secondes:>9.0f}"
                  f"   trop peu d'extraits pour conclure")
            continue
        valeurs = coherence(empreintes)
        etrangers = sum(1 for v in valeurs if v < ETRANGER)
        print(f"{voix:>6} {len(empreintes):>9} {secondes:>9.0f} "
              f"{stat.median(valeurs):>9.3f} {valeurs[len(valeurs) // 10]:>9.3f} "
              f"{valeurs[0]:>7.3f}  {etrangers:>4} / {len(valeurs)}")

    print("\n== repère : les grosses voix entre elles ==")
    agregats = {v: agreger(e) for v, e in grosses}
    identifiants = [v for v, _ in grosses]
    for i, un in enumerate(identifiants):
        for autre in identifiants[i + 1:]:
            print(f"  {un:>6} ↔ {autre:<6} {similarite(agregats[un], agregats[autre]):.3f}")

    print("\nUne voix moins cohérente que ses voisines mélange probablement deux")
    print("personnes. Plus cohérente qu'elles, c'est une seule personne bavarde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
