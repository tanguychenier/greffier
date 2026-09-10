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

from greffier.domain.models import Span

VOIX_LOCALE = "moi"

MARGE_DB = 6.0

PLANCHER_DB = -45.0

RECOLLAGE_S = 0.7

DUREE_MINIMALE_S = 0.8

@dataclass(frozen=True)
class Reglages:
    """De quoi ajuster sans toucher au code, et sans deviner les valeurs."""

    marge_db: float = MARGE_DB
    plancher_db: float = PLANCHER_DB
    recollage_s: float = RECOLLAGE_S
    duree_minimale_s: float = DUREE_MINIMALE_S

class WhoSpeaks(StrEnum):
    """Ce qu'une interface peut afficher pendant la réunion, sans modèle.

    La provenance suffit : le micro d'un côté, la boucle système de l'autre.
    Aucun calcul d'empreinte, donc une réponse immédiate à chaque trame.
    """

    PERSONNE = "personne"
    TOI = "toi"
    LES_AUTRES = "les autres"
    LES_DEUX = "les deux"

PART_VISIO = 0.05

def over_video(
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

def who_speaks(
    micro_db: float,
    systeme_db: float,
    reglages: Reglages | None = None,
) -> WhoSpeaks:
    """Qui tient la parole à cet instant, d'après les deux canaux."""
    r = reglages or Reglages()
    mic = micro_db > r.plancher_db
    system = systeme_db > r.plancher_db
    if mic and system:
        return WhoSpeaks.LES_DEUX if micro_db > systeme_db + r.marge_db else WhoSpeaks.LES_AUTRES
    if mic:
        return WhoSpeaks.TOI
    if system:
        return WhoSpeaks.LES_AUTRES
    return WhoSpeaks.PERSONNE

def local_turns(
    micro_db: list[float],
    systeme_db: list[float],
    pas_s: float,
    reglages: Reglages | None = None,
) -> list[Span]:
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

def _regrouper(locales: list[bool], pas_s: float, r: Reglages) -> list[Span]:
    """Assemble les trames en intervalles, en recollant les silences courts."""
    plages: list[tuple[int, int]] = []
    start: int | None = None
    dernier = 0
    for i, active in enumerate(locales):
        if active:
            if start is None:
                start = i
            dernier = i
        elif start is not None and (i - dernier) * pas_s > r.recollage_s:
            plages.append((start, dernier + 1))
            start = None
    if start is not None:
        plages.append((start, dernier + 1))

    return [
        Span(a * pas_s, b * pas_s)
        for a, b in plages
        if (b - a) * pas_s >= r.duree_minimale_s
    ]

def subtract(span: Span, autres: list[Span]) -> list[Span]:
    """Ce qui reste d'un intervalle quand on en ôte les autres.

    Sert à prélever une empreinte vocale sur ce qui est **vraiment** distant. La
    transcription coupe à la phrase, pas au changement de locuteur : un passage
    peut porter la fin d'une phrase locale, et l'empreinte tirée du tout mélange
    alors deux voix. Mesuré à l'essai : 0,6 s de voix locale dans un extrait de
    1,5 s suffisait à faire de la même personne deux participants distincts.
    """
    restes = [span]
    for autre in autres:
        suivants: list[Span] = []
        for reste in restes:
            if autre.end <= reste.start or autre.start >= reste.end:
                suivants.append(reste)
                continue
            if autre.start > reste.start:
                suivants.append(Span(reste.start, autre.start))
            if autre.end < reste.end:
                suivants.append(Span(autre.end, reste.end))
        restes = suivants
    return restes

def remove(turns: list[Span], locaux: list[Span]) -> list[Span]:
    """Ôte des tours distants ce qui recouvre un tour local.

    La segmentation tourne sur la boucle système seule, donc elle ne devrait
    jamais y voir la voix locale. Mais un participant qui parle en même temps
    laisse un tour à cheval, et laisser les deux ferait compter deux personnes
    là où une seule tient la parole. On tranche en faveur du canal, qui ne se
    trompe pas sur la provenance.
    """
    if not locaux:
        return turns
    restants: list[Span] = []
    for turn in turns:
        couvert = sum(
            max(0.0, min(turn.end, local.end) - max(turn.start, local.start))
            for local in locaux
        )
        if turn.duration <= 0 or couvert / turn.duration < 0.5:
            restants.append(turn)
    return restants
