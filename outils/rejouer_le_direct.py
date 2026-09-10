#!/usr/bin/env python3
"""Rejoue le fil du direct sur une réunion étiquetée, sans audio ni modèle.

Les empreintes sont déjà calculées ; ce qu'on rejoue, c'est la seule chose qui
décide en séance : **l'ordre du temps**. Le direct ne connaît que le passé,
alors que le recollage d'après réunion voit tout. Comparer les deux dit où se
trouve la marge de progrès — et sur la réunion du 2026-09-10, la réponse a
contredit l'intuition : aucun gradient de démarrage, le creux est au milieu.

La chronologie vient des tours de la réunion et non de l'ordre du cache : sans
elle, le chiffre ne mesure rien.

    python3 outils/rejouer_le_direct.py 2026-09-10_10h10_reunion

Les empreintes viennent du cache de « rejouer_recollage.py » : lance-le d'abord.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domaine.direct import Bloc, Fil  # noqa: E402
from greffier.domaine.modeles import Empreinte, Intervalle, Replique  # noqa: E402
from greffier.domaine.noms import reunir_les_homonymes  # noqa: E402
from greffier.emplacements import dossier_donnees  # noqa: E402

#: Tous les combien de phrases le fil recolle ses voix, comme en séance.
RECOLLAGE_TOUS_LES = 40

#: Combien de tranches de temps pour chercher un gradient.
TRANCHES = 6


def suite_chronologique(
    reunion: dict, par_voix: dict[str, list[Empreinte]], nommees: set[str]
) -> list[tuple[float, float, str, Empreinte]]:
    """Les tours dans l'ordre du temps, avec leur empreinte et leur vraie voix.

    La Nième empreinte d'une voix correspond au Nième tour de cette voix : c'est
    l'ordre dans lequel le cache a été construit, et c'est ce qui permet de
    retrouver la chronologie sans réécouter l'audio.
    """
    rangs: Counter = Counter()
    suite = []
    for tour in sorted(reunion["tours"], key=lambda t: float(t["debut"])):
        voix = str(tour["voix"])
        rang = rangs[voix]
        rangs[voix] += 1
        empreintes = par_voix.get(voix, [])
        if voix not in nommees or rang >= len(empreintes):
            continue
        suite.append(
            (float(tour["debut"]), float(tour["fin"]), voix, empreintes[rang])
        )
    return suite


def verite_nommee(reunion: dict) -> set[str]:
    """Les voix nommées, une par personne.

    Passe par la réunion des homonymes : sur la réunion du 2026-09-10, le
    fichier porte seize voix nommées dont **neuf « Laura »**. Les compter comme
    neuf personnes fausserait la vérité terrain autant que le compte rendu.
    """
    noms = {str(v): nom for v, nom in (reunion.get("noms") or {}).items()}
    poids: Counter = Counter()
    for tour in reunion["tours"]:
        poids[str(tour["voix"])] += float(tour["fin"]) - float(tour["debut"])
    appartenance = reunir_les_homonymes(noms, dict(poids))
    return {voix for voix, gardee in appartenance.items() if voix == gardee}


def rejouer(suite: list) -> tuple[Fil, list[tuple[str, int]], list[bool]]:
    """Refait le fil phrase par phrase, et dit lesquelles sont justes.

    Une voix du fil vaut pour la personne majoritaire qu'elle contient : le fil
    ne connaît pas les noms, et le juger sur ses identifiants n'aurait aucun
    sens.
    """
    fil = Fil()
    attribue: list[tuple[str, int]] = []
    for debut, fin, vraie, empreinte in suite:
        voix = fil.rattacher(empreinte=empreinte, locale=False)
        fil.inscrire(
            Bloc(
                repliques=(Replique(intervalle=Intervalle(debut, fin), texte="x"),),
                locale=False,
            ),
            voix,
        )
        attribue.append((vraie, len(fil.tours)))
        if len(attribue) % RECOLLAGE_TOUS_LES == 0:
            fil.recoller()
    fil.recoller()
    final = {t.numero: t.voix for t in fil.tours}
    groupes: dict[str, Counter] = {}
    for vraie, numero in attribue:
        groupes.setdefault(final.get(numero, "?"), Counter())[vraie] += 1
    majorite = {v: c.most_common(1)[0][0] for v, c in groupes.items()}
    justes = [majorite.get(final.get(n)) == vraie for vraie, n in attribue]
    return fil, attribue, justes


def main() -> int:
    analyse = argparse.ArgumentParser(description=__doc__)
    analyse.add_argument("reunion")
    arguments = analyse.parse_args()

    chemin = dossier_donnees() / "reunions" / f"{arguments.reunion}.json"
    cache = Path("/tmp/greffier-empreintes") / f"{arguments.reunion}.pickle"
    if not cache.exists():
        print("Les empreintes manquent : lance d'abord "
              "« outils/rejouer_recollage.py » sur cette réunion.", file=sys.stderr)
        return 1
    reunion = json.loads(chemin.read_text())
    par_voix = pickle.loads(cache.read_bytes())
    nommees = verite_nommee(reunion)
    if not nommees:
        print("Aucune voix nommée : il n'y a pas de vérité terrain à comparer.",
              file=sys.stderr)
        return 1

    suite = suite_chronologique(reunion, par_voix, nommees)
    if not suite:
        print("Aucun tour étiqueté.", file=sys.stderr)
        return 1
    fil, attribue, justes = rejouer(suite)

    print(f"{len(suite)} tours étiquetés, de {suite[0][0] / 60:.0f} "
          f"à {suite[-1][1] / 60:.0f} min")
    print(f"voix créées : {len(fil.voix) - 1} pour {len(nommees)} personnes nommées")
    print(f"justesse du direct : {sum(justes)}/{len(justes)} "
          f"= {sum(justes) / len(justes):.1%}")

    taille = len(justes) // TRANCHES
    print(f"\n{'tranche':>10} {'minutes':>16} {'phrases':>8} {'justesse':>9}")
    for i in range(TRANCHES):
        a = i * taille
        b = (i + 1) * taille if i < TRANCHES - 1 else len(justes)
        part = justes[a:b]
        print(f"{i + 1:>5}/{TRANCHES:<4} {suite[a][0] / 60:>7.0f} → "
              f"{suite[b - 1][1] / 60:<6.0f} {len(part):>8} "
              f"{sum(part) / len(part):>8.1%}")

    print("\n== ce que pèsent les voix du fil ==")
    final = {t.numero: t.voix for t in fil.tours}
    poids: Counter = Counter()
    tours: Counter = Counter()
    contenu: dict[str, Counter] = {}
    for vraie, numero in attribue:
        voix = final.get(numero, "?")
        tours[voix] += 1
        contenu.setdefault(voix, Counter())[vraie] += 1
    for tour in fil.tours:
        poids[final.get(tour.numero, "?")] += tour.intervalle.duree
    print(f"{'voix':>6} {'tours':>6} {'secondes':>9}  qui elle contient")
    for voix, secondes in poids.most_common():
        dit = ", ".join(f"{n} × {q}" for n, q in contenu.get(voix, Counter()).most_common())
        print(f"{voix:>6} {tours[voix]:>6} {secondes:>9.0f}  {dit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
