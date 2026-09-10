"""Ce que les participants d'une réunion doivent pouvoir savoir.

Un enregistrement de voix est une donnée biométrique. Dans un organisme public,
la base légale et l'information des personnes se documentent — et l'outil ne
portait rien de tout cela : ni mention au démarrage, ni trace dans le compte
rendu, ni moyen de savoir après coup si quelqu'un avait été prévenu.

Ce module ne décide pas de la politique : ce n'est pas au code de dire s'il faut
un consentement explicite, une information simple ou rien du tout — cela dépend
de la base légale retenue, qui est une décision d'organisation. Il fournit de
quoi **tracer** ce qui a été fait, pour que la réponse à « les participants
étaient-ils au courant ? » existe, quelle qu'elle soit.

Le principe retenu : ce qui n'est pas écrit n'a pas eu lieu. Une mention orale
faite en réunion ne se retrouve pas six mois plus tard ; une ligne dans le
compte rendu, oui.
"""

from __future__ import annotations

from enum import StrEnum


class Disclosure(StrEnum):
    """Ce qui a été fait vis-à-vis des participants."""

    RIEN = "rien"
    ANNONCE = "annoncé"
    AGREEMENT = "accord"

MENTIONS = {
    Disclosure.RIEN: (
        "Cette réunion a été enregistrée et transcrite automatiquement. "
        "L'information des participants n'a pas été tracée."
    ),
    Disclosure.ANNONCE: (
        "Cette réunion a été enregistrée et transcrite automatiquement, "
        "les participants en ayant été informés."
    ),
    Disclosure.AGREEMENT: (
        "Cette réunion a été enregistrée et transcrite automatiquement, "
        "avec l'accord des participants."
    ),
}

RAPPEL = (
    "Une voix est une donnée biométrique. Pense à prévenir les participants "
    "que la réunion est enregistrée — et note-le dans « conversation.information » "
    "pour que le compte rendu le dise."
)

def mention(disclosure: Disclosure) -> str:
    """La phrase à porter au compte rendu."""
    return MENTIONS[disclosure]

def to_draw(disclosure: Disclosure) -> bool:
    """Vrai s'il reste quelque chose à faire pour être en règle avec soi-même."""
    return disclosure is Disclosure.RIEN

def read(brut: str) -> Disclosure:
    """Ce que dit la configuration, ou « rien » si elle ne dit rien de valable.

    On retombe sur l'état le plus prudent : une valeur mal orthographiée ne doit
    pas faire écrire au compte rendu que les participants ont donné leur accord.
    """
    nu = brut.strip().casefold()
    for value in Disclosure:
        if nu == str(value).casefold():
            return value
    return Disclosure.RIEN
