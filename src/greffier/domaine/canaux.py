"""Qui parle, d'après le canal par lequel le son arrive.

L'enregistrement sépare matériellement deux sources : le micro d'un côté, ce que
jouent les haut-parleurs de l'autre. Une voix qui arrive par le micro est celle
de la personne qui enregistre ; une voix qui arrive par la boucle système est
celle d'un participant distant. Ce n'est pas une déduction, c'est un fait de
câblage, et aucun modèle n'a besoin d'être consulté pour l'établir.

La chaîne moyennait ces canaux avant de chercher les locuteurs. Sur une réunion
réelle, la voix de la personne qui enregistrait est arrivée 12 dB sous celle des
autres : moyennée, elle se retrouvait 18 dB sous le mélange, et la segmentation
ne l'a jamais vue. Treize minutes de parole absentes du compte rendu, sur une
réunion d'une heure. Ce module rend cette information au lieu de la détruire.

Il ne connaît ni ffmpeg ni sherpa-onnx : il reçoit des niveaux par trame, en
décibels, et rend des intervalles.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from greffier.domaine.modeles import Intervalle

#: Étiquette de la voix locale. Distincte des identifiants de la segmentation,
#: qui sont numériques, pour qu'aucune confusion ne soit possible.
VOIX_LOCALE = "moi"

#: De combien le micro doit dépasser la boucle système pour qu'on tienne la
#: parole pour locale. Une marge est nécessaire quand on écoute par
#: haut-parleurs : le micro réentend alors ce que jouent les enceintes.
MARGE_DB = 6.0

#: Sous ce niveau, le micro ne porte que le bruit de la pièce. Mesuré sur une
#: réunion réelle : ventilation et clavier tiennent entre -55 et -45 dB.
PLANCHER_DB = -45.0

#: Deux passages séparés de moins de cela appartiennent à la même prise de
#: parole : ce sont les silences d'une phrase, pas des tours différents.
RECOLLAGE_S = 0.7

#: En deçà, c'est un « oui », un « d'accord » ou un bruit. Les garder ferait
#: passer une réunion pour une succession de centaines de micro-tours.
DUREE_MINIMALE_S = 0.8


@dataclass(frozen=True)
class Reglages:
    """De quoi ajuster sans toucher au code, et sans deviner les valeurs."""

    marge_db: float = MARGE_DB
    plancher_db: float = PLANCHER_DB
    recollage_s: float = RECOLLAGE_S
    duree_minimale_s: float = DUREE_MINIMALE_S


class QuiParle(StrEnum):
    """Ce qu'une interface peut afficher pendant la réunion, sans modèle.

    La provenance suffit : le micro d'un côté, la boucle système de l'autre.
    Aucun calcul d'empreinte, donc une réponse immédiate à chaque trame.
    """

    PERSONNE = "personne"
    TOI = "toi"
    LES_AUTRES = "les autres"
    LES_DEUX = "les deux"


#: Part des trames où la boucle système doit dominer le micro pour qu'on tienne
#: la réunion pour distante. Mesuré : 57,7 % sur une visio d'une heure, 0,0 % sur
#: une réunion tenue autour d'une table. Cinq pour cent séparent les deux sans
#: la moindre ambiguïté.
PART_VISIO = 0.05


def en_visio(
    micro_db: list[float],
    systeme_db: list[float],
    reglages: Reglages | None = None,
) -> bool:
    """Dit si la réunion s'est tenue à distance, d'après les deux canaux.

    Le critère est **relatif**, et il a fallu s'y reprendre. Tester si la boucle
    système est non nulle ne marche pas : sur une réunion tenue autour d'une
    table, elle relevait -53 dB au lieu du silence attendu, du son ayant fui
    dedans à un moment. Conclure « visio » sur cette base attribuait toute la
    réunion à la personne qui enregistrait.

    Ce qui distingue vraiment les deux, c'est que dans une visio les autres
    dominent le micro une bonne partie du temps, puisqu'ils parlent par les
    haut-parleurs. Autour d'une table, jamais : tout le monde passe par le micro.
    """
    r = reglages or Reglages()
    utiles = min(len(micro_db), len(systeme_db))
    if utiles == 0:
        return False
    domine = sum(
        1
        for i in range(utiles)
        if systeme_db[i] > micro_db[i] + r.marge_db and systeme_db[i] > r.plancher_db
    )
    return domine / utiles >= PART_VISIO


def qui_parle(
    micro_db: float,
    systeme_db: float,
    reglages: Reglages | None = None,
) -> QuiParle:
    """Qui tient la parole à cet instant, d'après les deux canaux."""
    r = reglages or Reglages()
    micro = micro_db > r.plancher_db
    systeme = systeme_db > r.plancher_db
    if micro and systeme:
        # Les deux canaux sont actifs : c'est un vrai chevauchement si le micro
        # domine, sinon le micro ne fait que réentendre les haut-parleurs.
        return QuiParle.LES_DEUX if micro_db > systeme_db + r.marge_db else QuiParle.LES_AUTRES
    if micro:
        return QuiParle.TOI
    if systeme:
        return QuiParle.LES_AUTRES
    return QuiParle.PERSONNE


def tours_locaux(
    micro_db: list[float],
    systeme_db: list[float],
    pas_s: float,
    reglages: Reglages | None = None,
) -> list[Intervalle]:
    """Les moments où la personne qui enregistre parle elle-même.

    `micro_db` et `systeme_db` sont les niveaux par trame, dans le même
    découpage. `pas_s` est la durée d'une trame.

    Une trame compte comme locale quand le micro dépasse la boucle système d'au
    moins la marge **et** qu'il sort du bruit de fond. Les deux conditions sont
    nécessaires : la première seule retiendrait les silences de la réunion, où
    le bruit de la pièce domine une boucle muette.
    """
    r = reglages or Reglages()
    if pas_s <= 0:
        raise ValueError("le pas des trames doit être positif")

    utiles = min(len(micro_db), len(systeme_db))
    locales = [
        micro_db[i] > systeme_db[i] + r.marge_db and micro_db[i] > r.plancher_db
        for i in range(utiles)
    ]
    return _regrouper(locales, pas_s, r)


def _regrouper(locales: list[bool], pas_s: float, r: Reglages) -> list[Intervalle]:
    """Assemble les trames en intervalles, en recollant les silences courts."""
    plages: list[tuple[int, int]] = []
    debut: int | None = None
    dernier = 0
    for i, active in enumerate(locales):
        if active:
            if debut is None:
                debut = i
            dernier = i
        elif debut is not None and (i - dernier) * pas_s > r.recollage_s:
            plages.append((debut, dernier + 1))
            debut = None
    if debut is not None:
        plages.append((debut, dernier + 1))

    return [
        Intervalle(a * pas_s, b * pas_s)
        for a, b in plages
        if (b - a) * pas_s >= r.duree_minimale_s
    ]


def soustraire(intervalle: Intervalle, autres: list[Intervalle]) -> list[Intervalle]:
    """Ce qui reste d'un intervalle quand on en ôte les autres.

    Sert à prélever une empreinte vocale sur ce qui est **vraiment** distant. La
    transcription coupe à la phrase, pas au changement de locuteur : un passage
    peut porter la fin d'une phrase locale, et l'empreinte tirée du tout mélange
    alors deux voix. Mesuré à l'essai : 0,6 s de voix locale dans un extrait de
    1,5 s suffisait à faire de la même personne deux participants distincts.
    """
    restes = [intervalle]
    for autre in autres:
        suivants: list[Intervalle] = []
        for reste in restes:
            if autre.fin <= reste.debut or autre.debut >= reste.fin:
                suivants.append(reste)
                continue
            if autre.debut > reste.debut:
                suivants.append(Intervalle(reste.debut, autre.debut))
            if autre.fin < reste.fin:
                suivants.append(Intervalle(autre.fin, reste.fin))
        restes = suivants
    return restes


def retirer(tours: list[Intervalle], locaux: list[Intervalle]) -> list[Intervalle]:
    """Ôte des tours distants ce qui recouvre un tour local.

    La segmentation tourne sur la boucle système seule, donc elle ne devrait
    jamais y voir la voix locale. Mais un participant qui parle en même temps
    laisse un tour à cheval, et laisser les deux ferait compter deux personnes
    là où une seule tient la parole. On tranche en faveur du canal, qui ne se
    trompe pas sur la provenance.
    """
    if not locaux:
        return tours
    restants: list[Intervalle] = []
    for tour in tours:
        couvert = sum(
            max(0.0, min(tour.fin, local.fin) - max(tour.debut, local.debut))
            for local in locaux
        )
        if tour.duree <= 0 or couvert / tour.duree < 0.5:
            restants.append(tour)
    return restants
