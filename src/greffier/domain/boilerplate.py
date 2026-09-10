"""Écarte les génériques que le modèle de transcription invente.

Whisper a été entraîné sur des vidéos sous-titrées. Sur un signal faible — un
silence, un brouhaha, une tranche de deux secondes prise en présentiel — il
comble avec ce qu'il a le plus vu à cet endroit-là : le générique de fin.
« Sous-titrage réalisé par… », « Merci d'avoir regardé cette vidéo ! ». Ces
phrases n'ont pas été prononcées, et elles se retrouvaient dans le fil du
direct, puis dans le compte rendu comme si quelqu'un les avait dites.

La mise à niveau des canaux réduit le phénomène sans le supprimer : elle agit
sur le son, pas sur ce que le modèle en fait. Il faut donc aussi reconnaître ces
phrases.

**Prudence d'abord.** Une réplique n'est écartée que si elle est *entièrement*
un générique, ponctuation et casse mises de côté. « Merci » seul reste, « merci
d'avoir regardé cette vidéo » part. Rien n'est jamais retiré au milieu d'une
phrase réelle : mieux vaut laisser passer un générique que perdre une décision.
"""

from __future__ import annotations

import re
import unicodedata

from greffier.domain.language import LanguageProfile

_PONCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_ESPACES = re.compile(r"\s+")

def _nu(text: str) -> str:
    """Le texte sans accents, sans ponctuation, en minuscules.

    Le modèle écrit tantôt « Sous-titrage », tantôt « Sous titrage : », tantôt
    en majuscules : comparer les formes brutes en manquerait la moitié.
    """
    strip_accents = "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )
    return _ESPACES.sub(" ", _PONCTUATION.sub(" ", strip_accents)).strip()

def is_boilerplate(text: str, profil: LanguageProfile) -> bool:
    """Vrai si toute la réplique est un générique inventé par le modèle.

    La liste appartient à la langue : les génériques sont ce que le modèle a
    réellement écrit sur des silences, dans cette langue-là. Une langue sans
    liste observée n'en écarte aucun — mieux vaut garder une phrase inventée
    que retirer de la parole à quelqu'un sur une liste recopiée de mémoire.
    """
    return _nu(text) in profil.redaction.boilerplate

_BORNES_ANNOTATION = (("*", "*"), ("(", ")"), ("[", "]"), ("♪", "♪"), ("{", "}"))

def is_an_annotation(text: str) -> bool:
    """Vrai si toute la réplique est une annotation, pas de la parole.

    Même prudence que pour les génériques : la réplique doit être entièrement
    entre les bornes. « (rires) » part, « il a dit (à tort) que » reste — une
    parenthèse au milieu d'une phrase est de la parole, et la couper perdrait
    la phrase.
    """
    nu = text.strip()
    if len(nu) < 3:
        return False
    for ouvre, firm in _BORNES_ANNOTATION:
        if not (nu.startswith(ouvre) and nu.endswith(firm)):
            continue
        if ouvre != firm:
            # Une seule paire : « (a) et (b) » n'est pas une annotation, c'est
            # une phrase qui en contient deux.
            return firm not in nu[len(ouvre):-len(firm)]
        # Bornes identiques : deux marques encadrent bien une annotation, et
        # une ligne qui n'est que des marques en est une aussi — le modèle
        # écrit « ♪ ♪ ♪ » sur de la musique. Au-delà, « *a* et *b* » est une
        # phrase.
        return nu.count(ouvre) == 2 or not nu.replace(ouvre, "").strip()
    return False

