"""Le profil des langues qu'aucune règle éprouvée ne sert encore.

Détection éteinte, et c'est une correction, pas un renoncement. Mesuré sur les
vraies fonctions avec le profil français appliqué à de l'anglais :

    « Budget, on the other hand, is not settled. »  →  « Budget »
    « Anyway, on Monday we ship. »                  →  « Anyway »
    « Marketing, on our side, is ready. »           →  « Marketing »
    « I'm Lise and I'm the project manager. »      →  rien

Les motifs français ne se taisent pas hors du français : ils inventent des
participants et manquent les vraies présentations. Une réunion réelle à quatre
personnes en rendait six. Éteindre la détection laisse les voix en « Personne N »
— à nommer une fois dans l'onglet Voix, puis reconnues seules — ce qui est un
travail de plus pour l'utilisateur, mais un travail juste.

Le découpage, lui, reste prudent : sans savoir si la langue sépare ses mots par
des espaces, on compte les caractères, faute de quoi une transcription chinoise
valable passerait pour vide.
"""

from __future__ import annotations

from greffier.domain.language import Decoupage, Detection, LanguageProfile

NEUTRAL = LanguageProfile(
    code="",
    name="",
    detection=Detection(active=False),
    decoupage=Decoupage(mots_separes_par_des_espaces=False),
)
