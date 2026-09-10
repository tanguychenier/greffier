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

from greffier.domain.live import Block, LiveThread  # noqa: E402
from greffier.domain.models import Span, Utterance, Voiceprint  # noqa: E402
from greffier.domain.names import join_namesakes  # noqa: E402
from greffier.locations import data_folder  # noqa: E402

#: Tous les combien de phrases le fil recolle ses voix, comme en séance.
RECOLLAGE_TOUS_LES = 40

#: Combien de tranches de temps pour chercher un gradient.
TRANCHES = 6


def suite_chronologique(
    meeting: dict, per_voice: dict[str, list[Voiceprint]], nommees: set[str]
) -> list[tuple[float, float, str, Voiceprint]]:
    """Les tours dans l'ordre du temps, avec leur empreinte et leur vraie voix.

    La Nième empreinte d'une voix correspond au Nième tour de cette voix : c'est
    l'ordre dans lequel le cache a été construit, et c'est ce qui permet de
    retrouver la chronologie sans réécouter l'audio.
    """
    rangs: Counter = Counter()
    suite = []
    for turn in sorted(meeting["tours"], key=lambda t: float(t["debut"])):
        voice = str(turn["voix"])
        rank = rangs[voice]
        rangs[voice] += 1
        voiceprints = per_voice.get(voice, [])
        if voice not in nommees or rank >= len(voiceprints):
            continue
        suite.append(
            (float(turn["debut"]), float(turn["fin"]), voice, voiceprints[rank])
        )
    return suite


def verite_nommee(meeting: dict) -> set[str]:
    """Les voix nommées, une par personne.

    Passe par la réunion des homonymes : sur la réunion du 2026-09-10, le
    fichier porte seize voix nommées dont **neuf « Laura »**. Les compter comme
    neuf personnes fausserait la vérité terrain autant que le compte rendu.
    """
    names = {str(v): name for v, name in (meeting.get("noms") or {}).items()}
    poids: Counter = Counter()
    for turn in meeting["tours"]:
        poids[str(turn["voix"])] += float(turn["fin"]) - float(turn["debut"])
    membership = join_namesakes(names, dict(poids))
    return {voice for voice, gardee in membership.items() if voice == gardee}


def replay(suite: list) -> tuple[LiveThread, list[tuple[str, int]], list[bool]]:
    """Refait le fil phrase par phrase, et dit lesquelles sont justes.

    Une voix du fil vaut pour la personne majoritaire qu'elle contient : le fil
    ne connaît pas les noms, et le juger sur ses identifiants n'aurait aucun
    sens.
    """
    thread = LiveThread()
    attribue: list[tuple[str, int]] = []
    for start, end, vraie, voiceprint in suite:
        voice = thread.attach(voiceprint=voiceprint, locale=False)
        thread.record_turn(
            Block(
                utterances=(Utterance(span=Span(start, end), text="x"),),
                locale=False,
            ),
            voice,
        )
        attribue.append((vraie, len(thread.turns)))
        if len(attribue) % RECOLLAGE_TOUS_LES == 0:
            thread.stitch()
    thread.stitch()
    final = {t.number: t.voice for t in thread.turns}
    groupes: dict[str, Counter] = {}
    for vraie, number in attribue:
        groupes.setdefault(final.get(number, "?"), Counter())[vraie] += 1
    majorite = {v: c.most_common(1)[0][0] for v, c in groupes.items()}
    justes = [majorite.get(final.get(n)) == vraie for vraie, n in attribue]
    return thread, attribue, justes


def main() -> int:
    analyse = argparse.ArgumentParser(description=__doc__)
    analyse.add_argument("reunion")
    arguments = analyse.parse_args()

    path = data_folder() / "reunions" / f"{arguments.meeting}.json"
    cache = Path("/tmp/greffier-empreintes") / f"{arguments.meeting}.pickle"
    if not cache.exists():
        print("Les empreintes manquent : lance d'abord "
              "« outils/rejouer_recollage.py » sur cette réunion.", file=sys.stderr)
        return 1
    meeting = json.loads(path.read_text())
    per_voice = pickle.loads(cache.read_bytes())
    nommees = verite_nommee(meeting)
    if not nommees:
        print("Aucune voix nommée : il n'y a pas de vérité terrain à comparer.",
              file=sys.stderr)
        return 1

    suite = suite_chronologique(meeting, per_voice, nommees)
    if not suite:
        print("Aucun tour étiqueté.", file=sys.stderr)
        return 1
    thread, attribue, justes = replay(suite)

    print(f"{len(suite)} tours étiquetés, de {suite[0][0] / 60:.0f} "
          f"à {suite[-1][1] / 60:.0f} min")
    print(f"voix créées : {len(thread.voice) - 1} pour {len(nommees)} personnes nommées")
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
    final = {t.number: t.voice for t in thread.turns}
    poids: Counter = Counter()
    turns: Counter = Counter()
    content: dict[str, Counter] = {}
    for vraie, number in attribue:
        voice = final.get(number, "?")
        turns[voice] += 1
        content.setdefault(voice, Counter())[vraie] += 1
    for turn in thread.turns:
        poids[final.get(turn.number, "?")] += turn.span.duration
    print(f"{'voix':>6} {'tours':>6} {'secondes':>9}  qui elle contient")
    for voice, seconds in poids.most_common():
        dit = ", ".join(f"{n} × {q}" for n, q in content.get(voice, Counter()).most_common())
        print(f"{voice:>6} {turns[voice]:>6} {seconds:>9.0f}  {dit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
