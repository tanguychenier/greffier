"""Ce qui peut porter le nom d'une personne, et ce qui ne le peut pas.

Une entrée fautive dans la banque de voix ne se voit pas et ne se répare pas
toute seule : elle est reconnue à chaque réunion suivante, affirmée plutôt que
proposée, et elle confirme son erreur d'elle-même. Le contrôle doit donc se
faire au moment où le nom est saisi, une fois, et non après coup.

Le cas qui a motivé ce module est mesuré, pas imaginé : la banque du poste
portait une personne nommée **« A nommer »**, c'est-à-dire le libellé que
l'interface affiche dans la colonne « Nom » d'une voix qui n'en a pas encore.
Personne ne s'appelle ainsi. Le tour qu'a pris le geste importe peu — la
défense, elle, tient en une règle.
"""

from __future__ import annotations

import re
import unicodedata

LABELS = frozenset({
    "a nommer", "à nommer", "anommer", "sans nom", "inconnu", "inconnue",
    "les autres", "personne", "indetermine", "indéterminé", "moi", "toi",
    "voix", "non", "oui", "aucun", "aucune", "?", "-", "—",
})

LENGTH = (2, 30)

def _strip_accents(mot: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", mot)
        if unicodedata.category(c) != "Mn"
    )

def refusal(name: str) -> str:
    """Pourquoi ce nom ne peut pas entrer en banque, ou une chaîne vide.

    Rendre la raison plutôt qu'un booléen : elle s'affiche telle quelle, et
    « ce n'est pas un prénom » sans explication ferait recommencer la même
    saisie.
    """
    propre = " ".join(name.split())
    if not propre:
        return "Saisis un prénom."
    if len(propre) < LENGTH[0]:
        return "Un prénom fait au moins deux lettres."
    if len(propre) > LENGTH[1]:
        return "C'est trop long pour un prénom."
    replie = _strip_accents(propre).lower().strip(" .,;:!?")
    if replie in LABELS:
        return (
            f"« {propre} » est ce que Greffier affiche quand une voix n'a pas "
            "encore de nom, pas un prénom. Une telle entrée en banque serait "
            "reconnue à chaque réunion suivante."
        )
    if not re.search(r"[^\W\d_]", propre, flags=re.UNICODE):
        return "Un prénom porte des lettres."
    if re.fullmatch(r"[\d\W_]+", replie.replace(" ", "")):
        return "Un numéro de voix n'est pas un prénom."
    if replie.startswith("voix ") or replie.startswith("personne "):
        return f"« {propre} » est une étiquette de Greffier, pas un prénom."
    return ""

def acceptable(name: str) -> bool:
    return not refusal(name)

def normalise(name: str) -> str:
    """La forme sous laquelle un prénom est retenu.

    Les espaces se réduisent et la première lettre se met en capitale : sans
    cela, « michel » et « Michel » deviennent deux personnes distinctes dans la
    banque, et chacune n'a que la moitié des empreintes.
    """
    propre = " ".join(name.split())
    return propre[:1].upper() + propre[1:] if propre else propre
