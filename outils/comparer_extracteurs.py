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

from greffier.domain.voiceprints import aggregate, similarity, stitch  # noqa: E402
from greffier.locations import data_folder  # noqa: E402

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
WINDOW = 2.5
CACHE = Path("/tmp/greffier-extracteurs")


def download(name: str, target: Path) -> Path:
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"  téléchargement de {name}…", file=sys.stderr)
    partiel = target.with_suffix(".partiel")
    with urllib.request.urlopen(CATALOGUE + name) as flux, partiel.open("wb") as output:
        while morceau := flux.read(1 << 20):
            output.write(morceau)
    partiel.replace(target)
    return target


def voiceprints(model: Path, meeting: dict, key: str) -> list:
    """Une empreinte par fenêtre, dans l'ordre du temps. Mise en cache."""
    file = CACHE / f"{key}.pickle"
    if file.exists():
        return pickle.loads(file.read_bytes())

    import numpy as np
    import soundfile as sf

    from greffier.adapters.voiceprints_titanet import DUREE_MINIMALE, ExtracteurTitaNet

    extractor = ExtracteurTitaNet(model)
    rendered = []
    with sf.SoundFile(str(meeting["audio"])) as flux:
        frequency = flux.samplerate
        for turn in meeting["tours"]:
            at_instant = turn["debut"]
            while at_instant + DUREE_MINIMALE <= turn["fin"]:
                bout = min(at_instant + WINDOW, turn["fin"])
                flux.seek(int(at_instant * frequency))
                bloc = flux.read(int((bout - at_instant) * frequency),
                                 dtype="float32", always_2d=True)
                if len(bloc) >= DUREE_MINIMALE * frequency:
                    signal = np.ascontiguousarray(bloc.mean(axis=1))
                    rendered.append((at_instant, extractor.extract(signal, frequency)))
                at_instant = bout
    rendered.sort()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(pickle.dumps(rendered))
    return rendered


def verite(meeting: dict) -> list:
    """Qui parlait quand, d'après le recollage final de la réunion."""
    cache = Path("/tmp/greffier-empreintes") / f"{meeting['identifiant']}.pickle"
    if not cache.exists():
        raise SystemExit(
            "La vérité terrain manque : lance d'abord "
            "« outils/rejouer_recollage.py » sur cette réunion."
        )
    per_voice = pickle.loads(cache.read_bytes())
    membership = stitch(per_voice)
    return sorted(
        (t["debut"], t["fin"], membership.get(str(t["voix"]), str(t["voix"])))
        for t in meeting["tours"]
    )


def grade(etiquetees: list) -> dict:
    """L'écart entre « même personne » et « personnes différentes ».

    Sur les agrégats, parce que c'est la comparaison que fait le rattachement :
    une phrase contre une voix accumulée, jamais deux phrases entre elles.
    """
    par = defaultdict(list)
    for qui, voiceprint in etiquetees:
        par[qui].append(voiceprint)
    gros = sorted(par, key=lambda q: -len(par[q]))[:3]
    if len(gros) < 2:
        return {}
    memes, autres = [], []
    for qui in gros:
        reference = aggregate(par[qui][:40])
        memes += [similarity(e, reference) for e in par[qui][40:140]]
        for autre in gros:
            if autre != qui:
                autres += [similarity(e, reference) for e in par[autre][40:140]]
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

    path = data_folder() / "reunions" / f"{arguments.meeting}.json"
    meeting = json.loads(path.read_text())
    meeting["identifiant"] = arguments.meeting
    turns = verite(meeting)

    def qui(at_instant: float) -> str | None:
        for start, end, voice in turns:
            if start <= at_instant < end:
                return voice
        return None

    print(f"{len(turns)} tours, fenêtres de {WINDOW} s\n")
    print(f"{'modèle':16} {'même':>7} {'décile':>7} │ {'autre':>7} {'décile':>7} │ "
          f"{'marge':>7} {'ms/extrait':>11}")
    print("─" * 74)
    for key, name in CANDIDATS.items():
        model = download(name, CACHE / name)
        depart = time.time()
        extraits = voiceprints(model, meeting, key)
        cout = 1000 * (time.time() - depart) / max(1, len(extraits))
        etiquetees = [(qui(t), e) for t, e in extraits]
        scores = grade([(q, e) for q, e in etiquetees if q])
        if not scores:
            print(f"{key:16} pas assez de matière étiquetée")
            continue
        print(f"{key:16} {scores['meme']:7.3f} {scores['meme_bas']:7.3f} │ "
              f"{scores['autre']:7.3f} {scores['autre_haut']:7.3f} │ "
              f"{scores['marge']:+7.3f} {cout:10.1f}")
    print("\nLa marge est ce qui décide : c'est la place qui reste entre le "
          "premier décile\ndes mêmes et le neuvième des autres. Négative, aucun "
          "seuil ne les sépare.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
