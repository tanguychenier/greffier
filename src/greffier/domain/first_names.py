"""What may carry a person's name, and what may not.

The voice bank keeps voiceprints under a name: a label from the interface
landing in there poisons the recognition of every later meeting.
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
    """Why this name cannot enter the bank, or an empty string."""
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
    """The form a first name is kept under."""
    propre = " ".join(name.split())
    return propre[:1].upper() + propre[1:] if propre else propre
