"""Ce qu'une sauvegarde emporte, et combien on en garde.

Mesuré sur ce poste : 1,1 Go d'enregistrements contre 3 Mo pour tout le reste
— réunions transcrites, comptes rendus, banque de voix, contexte appris,
conversations. Le rapport est de 350 pour 1, et c'est ce qui rend une sauvegarde
possible : **on ne sauvegarde pas l'audio**.

Ce n'est pas un renoncement. Une transcription se refait depuis l'audio, mais
l'audio ne se refait pas du tout — sauf qu'une réunion transcrite dont l'audio
manque reste une réunion utilisable, tandis qu'un audio dont on a perdu la
transcription, l'attribution des voix et le compte rendu est un fichier de
115 Mo par heure que personne ne réécoutera. Ce qui porte le travail, c'est le
texte.

La banque de voix compte autant que les réunions : c'est elle qui a été
constituée un nom à la fois, par un humain, et elle ne se reconstitue pas depuis
autre chose.

Ce module ne touche à aucun fichier : il dit quoi prendre et quoi jeter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CONTENT = (
    "banque-de-voix",
    "reunions",
    "comptes-rendus",
    "transcriptions",
    "conversations",
    "questions",
    "direct",
    "propositions",
)

ECARTES = {
    "enregistrements": "l'audio, 115 Mo par heure — c'est lui qui rend une "
                       "sauvegarde impossible, et une réunion transcrite reste "
                       "utilisable sans lui",
    "modeles": "2 Go de modèles, retéléchargeables par l'installeur",
    "corpus": "un corpus public, retéléchargeable",
    "extraits": "des extraits recalculables depuis l'audio",
    "sauvegardes": "les sauvegardes elles-mêmes",
    "lectures": "des lectures à voix haute, refabricables",
}

KEPT = 7

@dataclass(frozen=True, slots=True)
class Nom:
    """Le nom d'une sauvegarde : sa date, jusqu'à la minute.

    À la minute et non au jour : on sauvegarde avant une opération risquée, et
    deux sauvegardes du même jour doivent pouvoir coexister.
    """

    quand: datetime

    def __str__(self) -> str:
        return f"greffier-{self.quand:%Y-%m-%d_%Hh%M}"

    @staticmethod
    def read(name: str) -> datetime | None:
        """La date d'une sauvegarde d'après son nom, ou None si ce n'en est pas une."""
        if not name.startswith("greffier-"):
            return None
        try:
            return datetime.strptime(name[len("greffier-"):], "%Y-%m-%d_%Hh%M")
        except ValueError:
            return None

def to_erase(names: list[str], kept: int = KEPT) -> list[str]:
    """Les sauvegardes en trop, les plus anciennes d'abord.

    Ne rend jamais la plus récente, quel que soit le compte demandé : une
    rotation qui peut tout effacer n'est pas une rotation, c'est une purge.
    """
    datees = [(Nom.read(name), name) for name in names]
    connues = sorted(
        ((quand, name) for quand, name in datees if quand is not None),
        reverse=True,
    )
    if len(connues) <= max(1, kept):
        return []
    return [name for _, name in connues[max(1, kept):]]
