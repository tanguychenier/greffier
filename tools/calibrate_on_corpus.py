#!/usr/bin/env python3
"""Mesure les seuils de reconnaissance sur un corpus public de réunions.

Le calibrage du dépôt (`docs/calibrage.md`) repose sur des enregistrements
faits ici, et il lui manque la mesure qui compte le plus : **la même personne,
sur deux séances différentes**. C'est elle qui dit si `SEUIL_RECONNAISSANCE`
est bien placé — un seuil trop haut ne reconnaît plus personne d'une réunion à
l'autre, un seuil trop bas confond deux collègues.

Le corpus AMI la fournit : ses réunions vont par séries, avec les **mêmes
participants**, et chacun porte son propre micro-casque. Deux fichiers
« Headset-N » de deux réunions d'une même série sont donc la même personne à
deux séances, sans annotation à interpréter ni supposition à faire.

Usage :

    python3 tools/calibrate_on_corpus.py <dossier du corpus>

Ce que ce script ne fait pas : il ne modifie aucun seuil. Il mesure et affiche.
Déplacer un seuil est une décision qui se prend en regardant les nombres, pas
un ajustement automatique — c'est ce qui distingue un calibrage d'un réglage
au hasard.

Le corpus AMI est distribué sous licence CC BY 4.0 (University of Edinburgh).
Il n'est pas versionné ici : seul cet outil l'est.
"""

from __future__ import annotations

import re
import sys
from itertools import combinations
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

#: Secondes lues au milieu de l'enregistrement. Le début d'une réunion AMI
#: porte des consignes lues et des silences ; le milieu porte de la discussion.
DURATION = 240.0

#: Un micro-casque AMI capte **aussi** les voisins de table, et son porteur ne
#: parle qu'une fraction du temps. Prendre l'extrait tel quel donne une
#: empreinte qui mélange plusieurs voix, du silence et de la respiration :
#: mesuré, la même personne à deux séances retombait alors à 0,149 tandis que
#: deux personnes différentes montaient à 0,280 — les deux nuages se
#: chevauchaient, ce qui signalait la méthode et non le seuil.
#:
#: On ne garde donc que les fenêtres les plus fortes : sur son propre micro, le
#: porteur est de loin le plus près, et son niveau le sépare nettement des
#: voix qui traversent la table.
WINDOW = 1.0
PART_RETENUE = 0.25

#: « ES2002a.Headset-0.wav » → série ES2002, séance a, participant 0.
_NAME = re.compile(r"^(?P<serie>[A-Z]{2}\d{4})(?P<seance>[a-z])\.Headset-(?P<qui>\d+)")


def situer(file: Path) -> tuple[str, str, str] | None:
    trouve = _NAME.match(file.name)
    if trouve is None:
        return None
    return (trouve["serie"], trouve["seance"], trouve["qui"])


def empreinte_de(file: Path, extractor) -> object | None:
    """L'empreinte de la voix **du porteur** du micro, et de lui seul.

    Les fenêtres les plus fortes sont recollées bout à bout, les autres jetées.
    C'est ce qui écarte les silences, la respiration et les voix qui traversent
    la table — sans quoi l'empreinte n'appartient à personne.
    """
    import numpy as np
    import soundfile as sf

    info = sf.info(str(file))
    depart = max(0, int((info.frames - DURATION * info.samplerate) / 2))
    data, frequency = sf.read(
        str(file), start=depart,
        frames=int(DURATION * info.samplerate), dtype="float32", always_2d=True,
    )
    mono = data.mean(axis=1)
    if float(np.abs(mono).max()) < 1e-4:
        return None

    par_fenetre = int(WINDOW * frequency)
    entieres = len(mono) // par_fenetre
    if entieres < 4:
        return extractor.extract(mono, frequency)
    fenetres = mono[:entieres * par_fenetre].reshape(entieres, par_fenetre)
    # Énergie efficace par fenêtre : c'est le niveau, pas un maximum ponctuel
    # qu'un claquement suffirait à faire monter.
    levels = np.sqrt((fenetres.astype(np.float64) ** 2).mean(axis=1))
    combien = max(4, int(entieres * PART_RETENUE))
    retenues = np.argsort(levels)[-combien:]
    return extractor.extract(
        fenetres[np.sort(retenues)].reshape(-1).astype(np.float32), frequency
    )


def main() -> int:
    from greffier.adapters.configuration import Config
    from greffier.adapters.voiceprints_titanet import TitaNetExtractor
    from greffier.domain.voiceprints import (
        MINIMUM_MARGIN,
        RECOGNITION_THRESHOLD,
        similarity,
    )

    folder = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else (
        Config().paths.data / "corpus"
    )
    files = sorted(path for path in folder.glob("*.Headset-*.wav"))
    if len(files) < 2:
        print(f"Il faut au moins deux enregistrements « Headset-N » dans {folder}.")
        print("Le script d'exemple les prend dans le corpus AMI, séries ES2002a/b.")
        return 1

    model = Config().paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
    if not model.exists():
        print(f"Modèle d'empreintes absent : {model}")
        return 1
    extractor = TitaNetExtractor(model)

    print(f"{len(files)} enregistrement(s), {DURATION:.0f} s lus au milieu, "
          f"les {PART_RETENUE:.0%} de fenêtres les plus fortes retenues\n")
    voiceprints: dict[tuple[str, str, str], object] = {}
    for file in files:
        situation = situer(file)
        if situation is None:
            print(f"  ignoré, nom non reconnu : {file.name}")
            continue
        voiceprint = empreinte_de(file, extractor)
        if voiceprint is None:
            print(f"  ignoré, muet : {file.name}")
            continue
        voiceprints[situation] = voiceprint
        serie, seance, qui = situation
        print(f"  {serie}{seance} participant {qui}")

    memes: list[float] = []
    autres: list[float] = []
    print("\nRessemblances mesurées :\n")
    for (un, autre) in combinations(sorted(voiceprints), 2):
        value = similarity(voiceprints[un], voiceprints[autre])  # type: ignore[arg-type]
        meme_personne = un[0] == autre[0] and un[2] == autre[2]
        meme_seance = un[1] == autre[1]
        if meme_personne and not meme_seance:
            quoi = "MÊME personne, deux séances"
            memes.append(value)
        elif meme_personne:
            quoi = "même personne, même séance"
        else:
            quoi = "personnes différentes"
            autres.append(value)
        print(f"  {value:.3f}  {quoi:<28} "
              f"{un[0]}{un[1]}·{un[2]} / {autre[0]}{autre[1]}·{autre[2]}")

    print(f"\nSeuil en vigueur : {RECOGNITION_THRESHOLD:.2f} "
          f"(marge minimale {MINIMUM_MARGIN:.2f})")
    if memes:
        print(f"  même personne, deux séances : {min(memes):.3f} à {max(memes):.3f}")
        sous = [value for value in memes if value < RECOGNITION_THRESHOLD]
        if sous:
            print(f"  ⚠ {len(sous)} paire(s) sous le seuil : ces personnes ne seraient")
            print("    pas reconnues d'une réunion à l'autre.")
    if autres:
        print(f"  personnes différentes       : {min(autres):.3f} à {max(autres):.3f}")
        au_dessus = [value for value in autres if value >= RECOGNITION_THRESHOLD]
        if au_dessus:
            print(f"  ⚠ {len(au_dessus)} paire(s) au-dessus du seuil : deux personnes")
            print("    différentes seraient confondues.")
    if memes and autres and max(autres) < min(memes):
        print(f"\n  Les deux nuages sont séparés : tout seuil entre {max(autres):.3f} "
              f"et {min(memes):.3f} sépare correctement.")
    elif memes and autres:
        # Le cas ordinaire dès qu'on mesure assez de paires. Ce qui compte
        # alors n'est plus « quel seuil sépare » mais « que coûte chaque
        # seuil » : c'est ce tableau qui permet de décider, et une première
        # mesure sur six paires avait laissé croire à une séparation nette.
        print("\n  Les nuages se chevauchent : aucun seuil ne sépare. Ce que "
              "chacun coûte :\n")
        print(f"    {'seuil':>6}  {'non reconnu(s)':>15}  {'confusion(s)':>13}")
        for threshold in (0.70, 0.60, 0.50, 0.45, 0.40, 0.30):
            manques = sum(1 for value in memes if value < threshold)
            confusions = sum(1 for value in autres if value >= threshold)
            print(f"    {threshold:>6.2f}  {manques:>7}/{len(memes):<7}  "
                  f"{confusions:>6}/{len(autres):<6}")
        print("\n  Une confusion écrit le nom de quelqu'un d'autre dans un "
              "compte rendu ;\n  un défaut de reconnaissance laisse une voix "
              "à nommer d'un clic. Les deux\n  ne se valent pas.")

    print("\n  Réserve : AMI ne garantit pas que le participant N garde le même"
          "\n  micro d'une séance à l'autre. Une part du chevauchement peut donc"
          "\n  être un artefact d'étiquetage plutôt que de timbre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
