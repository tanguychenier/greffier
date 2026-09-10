#!/usr/bin/env python3
"""Comparer des extracteurs d'empreintes sur une réunion déjà étiquetée.

Le choix d'un modèle d'empreintes décide de tout ce qui suit : le seuil de
rattachement, le nombre de voix affichées, la justesse des attributions. Il a
été fait une fois, au début du projet, et jamais remesuré — alors que le
catalogue du moteur en propose vingt et un.

Ce que cet outil mesure n'est pas la précision sur un jeu de reconnaissance de
locuteur, où tous ces modèles sont excellents. C'est la seule chose qui compte
ici : **sur des extraits courts, l'écart entre "même personne" et "personnes
différentes"**. C'est cet écart qui rend un seuil possible, et c'est lui qui
manquait quand le fil affichait cent onze voix.

    python3 outils/comparer_extracteurs.py 2026-09-09_16h36_reunion

La vérité terrain vient du recollage final de la réunion, qui a été contrôlé
contre les noms posés à la main. Les empreintes sont mises en cache par modèle :
le calcul coûte quelques minutes, la comparaison ensuite est immédiate.

**Ne pas lancer pendant une réunion** : l'extraction prend tout le processeur
que la transcription en direct utilise.
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics as stat
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domaine.empreintes import agreger, recoller, similarite  # noqa: E402
from greffier.emplacements import dossier_donnees  # noqa: E402

CATALOGUE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/")

#: Les candidats, et pourquoi chacun.
#:
#: TitaNet est celui en place. Les autres sont réputés meilleurs sur les
#: classements de vérification du locuteur, mais ces classements portent sur des
#: extraits de plusieurs secondes, prononcés seul devant un micro — ce qui n'est
#: pas notre cas. D'où la mesure.
CANDIDATS = {
    "titanet_large": "nemo_en_titanet_large.onnx",
    "campplus_LM": "wespeaker_en_voxceleb_CAM++_LM.onnx",
    "resnet293_LM": "wespeaker_en_voxceleb_resnet293_LM.onnx",
    "eres2netv2": "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
}

#: La longueur des extraits mesurés. C'est celle d'un bloc de tranche en direct,
#: donc celle où le choix du modèle se joue.
FENETRE = 2.5
CACHE = Path("/tmp/greffier-extracteurs")


def telecharger(nom: str, cible: Path) -> Path:
    if cible.exists():
        return cible
    cible.parent.mkdir(parents=True, exist_ok=True)
    print(f"  téléchargement de {nom}…", file=sys.stderr)
    partiel = cible.with_suffix(".partiel")
    with urllib.request.urlopen(CATALOGUE + nom) as flux, partiel.open("wb") as sortie:
        while morceau := flux.read(1 << 20):
            sortie.write(morceau)
    partiel.replace(cible)
    return cible


def empreintes(modele: Path, reunion: dict, clef: str) -> list:
    """Une empreinte par fenêtre, dans l'ordre du temps. Mise en cache."""
    fichier = CACHE / f"{clef}.pickle"
    if fichier.exists():
        return pickle.loads(fichier.read_bytes())

    import numpy as np
    import soundfile as sf

    from greffier.adaptateurs.empreintes_titanet import DUREE_MINIMALE, ExtracteurTitaNet

    extracteur = ExtracteurTitaNet(modele)
    rendu = []
    with sf.SoundFile(str(reunion["audio"])) as flux:
        frequence = flux.samplerate
        for tour in reunion["tours"]:
            instant = tour["debut"]
            while instant + DUREE_MINIMALE <= tour["fin"]:
                bout = min(instant + FENETRE, tour["fin"])
                flux.seek(int(instant * frequence))
                bloc = flux.read(int((bout - instant) * frequence),
                                 dtype="float32", always_2d=True)
                if len(bloc) >= DUREE_MINIMALE * frequence:
                    signal = np.ascontiguousarray(bloc.mean(axis=1))
                    rendu.append((instant, extracteur.extraire(signal, frequence)))
                instant = bout
    rendu.sort()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_bytes(pickle.dumps(rendu))
    return rendu


def verite(reunion: dict) -> list:
    """Qui parlait quand, d'après le recollage final de la réunion."""
    cache = Path("/tmp/greffier-empreintes") / f"{reunion['identifiant']}.pickle"
    if not cache.exists():
        raise SystemExit(
            "La vérité terrain manque : lance d'abord "
            "« outils/rejouer_recollage.py » sur cette réunion."
        )
    par_voix = pickle.loads(cache.read_bytes())
    appartenance = recoller(par_voix)
    return sorted(
        (t["debut"], t["fin"], appartenance.get(str(t["voix"]), str(t["voix"])))
        for t in reunion["tours"]
    )


def noter(etiquetees: list) -> dict:
    """L'écart entre « même personne » et « personnes différentes ».

    Sur les agrégats, parce que c'est la comparaison que fait le rattachement :
    une phrase contre une voix accumulée, jamais deux phrases entre elles.
    """
    par = defaultdict(list)
    for qui, empreinte in etiquetees:
        par[qui].append(empreinte)
    gros = sorted(par, key=lambda q: -len(par[q]))[:3]
    if len(gros) < 2:
        return {}
    memes, autres = [], []
    for qui in gros:
        reference = agreger(par[qui][:40])
        memes += [similarite(e, reference) for e in par[qui][40:140]]
        for autre in gros:
            if autre != qui:
                autres += [similarite(e, reference) for e in par[autre][40:140]]
    if len(memes) < 10 or len(autres) < 10:
        return {}
    memes.sort()
    autres.sort()
    return {
        "meme": stat.median(memes),
        "meme_bas": memes[len(memes) // 10],
        "autre": stat.median(autres),
        "autre_haut": autres[9 * len(autres) // 10],
        # Ce qui décide : la place qui reste entre les deux distributions. Un
        # écart négatif veut dire qu'aucun seuil ne les sépare proprement.
        "marge": memes[len(memes) // 10] - autres[9 * len(autres) // 10],
    }


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("reunion")
    arguments = parseur.parse_args()

    chemin = dossier_donnees() / "reunions" / f"{arguments.reunion}.json"
    reunion = json.loads(chemin.read_text())
    reunion["identifiant"] = arguments.reunion
    tours = verite(reunion)

    def qui(instant: float) -> str | None:
        for debut, fin, voix in tours:
            if debut <= instant < fin:
                return voix
        return None

    print(f"{len(tours)} tours, fenêtres de {FENETRE} s\n")
    print(f"{'modèle':16} {'même':>7} {'décile':>7} │ {'autre':>7} {'décile':>7} │ "
          f"{'marge':>7} {'ms/extrait':>11}")
    print("─" * 74)
    for clef, nom in CANDIDATS.items():
        modele = telecharger(nom, CACHE / nom)
        depart = time.time()
        extraits = empreintes(modele, reunion, clef)
        cout = 1000 * (time.time() - depart) / max(1, len(extraits))
        etiquetees = [(qui(t), e) for t, e in extraits]
        note = noter([(q, e) for q, e in etiquetees if q])
        if not note:
            print(f"{clef:16} pas assez de matière étiquetée")
            continue
        print(f"{clef:16} {note['meme']:7.3f} {note['meme_bas']:7.3f} │ "
              f"{note['autre']:7.3f} {note['autre_haut']:7.3f} │ "
              f"{note['marge']:+7.3f} {cout:10.1f}")
    print("\nLa marge est ce qui décide : c'est la place qui reste entre le "
          "premier décile\ndes mêmes et le neuvième des autres. Négative, aucun "
          "seuil ne les sépare.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
