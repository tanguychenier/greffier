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

from greffier.domaine import empreintes as domaine  # noqa: E402
from greffier.domaine.modeles import Empreinte, Intervalle  # noqa: E402
from greffier.emplacements import dossier_donnees  # noqa: E402


def empreintes_par_voix(reunion: dict, cache: Path) -> dict[str, list[Empreinte]]:
    """Une liste d'empreintes par voix, calculée une fois et gardée."""
    if cache.exists():
        return pickle.loads(cache.read_bytes())

    import numpy as np
    import soundfile as sf

    from greffier.adaptateurs.empreintes_titanet import (
        DUREE_MAXIMALE,
        DUREE_MINIMALE,
        ExtracteurTitaNet,
    )

    modele = dossier_donnees() / "modeles/diarisation/nemo_en_titanet_large.onnx"
    extracteur = ExtracteurTitaNet(modele)

    par_voix: dict[str, list[Intervalle]] = defaultdict(list)
    for tour in reunion["tours"]:
        par_voix[str(tour["voix"])].append(Intervalle(tour["debut"], tour["fin"]))

    resultat: dict[str, list[Empreinte]] = defaultdict(list)
    # Un seul parcours du fichier : `extraire_intervalles` le relit en entier à
    # chaque voix, ce qui ferait 298 lectures d'un fichier de 531 Mo.
    with sf.SoundFile(str(reunion["audio"])) as fichier:
        frequence = fichier.samplerate
        total = sum(len(v) for v in par_voix.values())
        fait = 0
        for voix, intervalles in par_voix.items():
            for intervalle in intervalles:
                fait += 1
                if fait % 100 == 0:
                    print(f"  {fait}/{total} extraits…", file=sys.stderr)
                if intervalle.duree < DUREE_MINIMALE:
                    continue
                debut, fin = intervalle.debut, intervalle.fin
                if fin - debut > DUREE_MAXIMALE:
                    milieu = (debut + fin) / 2
                    debut, fin = milieu - DUREE_MAXIMALE / 2, milieu + DUREE_MAXIMALE / 2
                fichier.seek(int(debut * frequence))
                bloc = fichier.read(int((fin - debut) * frequence), dtype="float32",
                                    always_2d=True)
                if len(bloc) < DUREE_MINIMALE * frequence:
                    continue
                signal = np.ascontiguousarray(bloc.mean(axis=1))
                resultat[voix].append(extracteur.extraire(signal, frequence))

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(dict(resultat)))
    return dict(resultat)


def noter(appartenance: dict[str, str], reunion: dict,
          par_voix: dict[str, list[Empreinte]]) -> dict:
    """Ce que vaut un recollage, contre les noms posés à la main."""
    verite = {str(v): n for v, n in reunion["noms"].items()}
    duree = defaultdict(float)
    for tour in reunion["tours"]:
        duree[appartenance.get(str(tour["voix"]), str(tour["voix"]))] += tour["fin"] - tour["debut"]

    groupes: dict[str, Counter] = defaultdict(Counter)
    for voix, nom in verite.items():
        groupes[appartenance.get(voix, voix)][nom] += sum(
            e.duree_source for e in par_voix.get(voix, [])) or 1.0

    melanges = {g: dict(c) for g, c in groupes.items() if len(c) > 1}
    eclats = Counter()
    for c in groupes.values():
        eclats[c.most_common(1)[0][0]] += 1
    total = sum(duree.values()) or 1.0
    gros = sorted(duree.items(), key=lambda x: -x[1])[:6]
    return {
        "voix": len(set(appartenance.values())),
        "melanges": melanges,
        "eclats": dict(eclats),
        "gros": [(g, round(s), round(100 * s / total)) for g, s in gros],
    }


def adoption(par_voix, seuil, marge, matiere) -> dict[str, str]:
    """Rattache les petits groupes au grand qui leur ressemble le plus.

    Le recollage par paires s'arrête dès qu'aucune paire ne franchit son seuil,
    et laisse alors des centaines de fragments isolés. La question posée ici est
    celle de la banque de voix, à l'intérieur d'une seule réunion : « lequel des
    groupes établis ressemble le plus, et **nettement** plus ». Seuil et marge,
    donc, et non un seuil seul.
    """
    appartenance = domaine.fusionner_voix(par_voix)
    groupes: dict[str, list[Empreinte]] = defaultdict(list)
    for voix, vers in appartenance.items():
        groupes[vers].extend(par_voix.get(voix, []))
    groupes = {g: e for g, e in groupes.items() if e}
    matieres = {g: sum(x.duree_source for x in e) for g, e in groupes.items()}
    etablis = {g: domaine.agreger(e) for g, e in groupes.items() if matieres[g] >= matiere}
    if not etablis:
        return appartenance
    for petit, empreintes in groupes.items():
        if petit in etablis:
            continue
        agregat = domaine.agreger(empreintes)
        classement = sorted(
            ((domaine.similarite(agregat, a), g) for g, a in etablis.items()),
            key=lambda x: (-x[0], x[1]),
        )
        meilleur, gagnant = classement[0]
        second = classement[1][0] if len(classement) > 1 else -1.0
        if meilleur >= seuil and meilleur - second >= marge:
            for voix, vers in appartenance.items():
                if vers == petit:
                    appartenance[voix] = gagnant
    return appartenance


def consolidation(par_voix, seuil_adoption, marge, matiere, seuil_final) -> dict[str, str]:
    """Adoption, puis les groupes établis se comparent entre eux.

    Une fois les fragments rattachés, un groupe établi porte des minutes de
    parole et non plus quelques secondes : son agrégat cesse d'être bruité, et
    deux groupes qui sont la même personne peuvent enfin se reconnaître à un
    seuil que des fragments n'auraient pas mérité.
    """
    appartenance = adoption(par_voix, seuil_adoption, marge, matiere)
    while True:
        groupes: dict[str, list[Empreinte]] = defaultdict(list)
        for voix, vers in appartenance.items():
            groupes[vers].extend(par_voix.get(voix, []))
        etablis = {g: e for g, e in groupes.items()
                   if sum(x.duree_source for x in e) >= matiere}
        agregats = {g: domaine.agreger(e) for g, e in etablis.items()}
        noms = sorted(agregats)
        meilleure = None
        for i, a in enumerate(noms):
            for b in noms[i + 1:]:
                score = domaine.similarite(agregats[a], agregats[b])
                if score >= seuil_final and (meilleure is None or score > meilleure[0]):
                    meilleure = (score, a, b)
        if meilleure is None:
            return appartenance
        _, garde, absorbe = meilleure
        if sum(x.duree_source for x in etablis[absorbe]) > sum(
                x.duree_source for x in etablis[garde]):
            garde, absorbe = absorbe, garde
        for voix, vers in appartenance.items():
            if vers == absorbe:
                appartenance[voix] = garde


def significatives(appartenance, reunion, minimum=10.0) -> int:
    duree = defaultdict(float)
    for tour in reunion["tours"]:
        duree[appartenance.get(str(tour["voix"]), str(tour["voix"]))] += (
            tour["fin"] - tour["debut"])
    return sum(1 for d in duree.values() if d >= minimum)


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("reunion")
    arguments = parseur.parse_args()

    chemin = dossier_donnees() / "reunions" / f"{arguments.reunion}.json"
    reunion = json.loads(chemin.read_text())
    cache = Path("/tmp/greffier-empreintes") / f"{arguments.reunion}.pickle"
    print(f"Empreintes de {arguments.reunion}…", file=sys.stderr)
    par_voix = empreintes_par_voix(reunion, cache)
    print(f"{len(par_voix)} voix portent au moins une empreinte.\n")

    print("== recollage actuel, par seuil ==")
    for seuil in (0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45):
        note = noter(domaine.fusionner_voix(par_voix, seuil=seuil), reunion, par_voix)
        print(f"seuil {seuil:.2f} → {note['voix']:4d} voix, "
              f"éclats {note['eclats']}, mélanges {len(note['melanges'])}")

    print("\n== recollage puis adoption des petits groupes ==")
    for seuil in (0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30):
        for marge in (0.0, 0.05, 0.10):
            note = noter(adoption(par_voix, seuil, marge, 30.0), reunion, par_voix)
            print(f"seuil {seuil:.2f} marge {marge:.2f} → {note['voix']:4d} voix, "
                  f"éclats {note['eclats']}, mélanges {len(note['melanges'])}, "
                  f"gros {note['gros'][:4]}")
    print("\n== adoption puis consolidation des établis ==")
    for adopt in (0.45, 0.40, 0.35):
        for final in (0.70, 0.65, 0.60, 0.55, 0.50):
            a = consolidation(par_voix, adopt, 0.0, 30.0, final)
            note = noter(a, reunion, par_voix)
            print(f"adoption {adopt:.2f} / consolidation {final:.2f} → "
                  f"{note['voix']:4d} voix ({significatives(a, reunion)} significatives), "
                  f"éclats {note['eclats']}, mélanges {len(note['melanges'])}, "
                  f"gros {note['gros'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
