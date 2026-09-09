"""Ce qu'on garde d'une réunion, et pendant combien de temps.

Mesuré sur un poste après deux semaines d'usage : 1,1 Go d'enregistrements
contre 3 Mo pour tout le reste — transcriptions, comptes rendus, fils du direct,
banque de voix réunis. La question de la place ne concerne donc que l'audio, et
elle ne se règle pas en effaçant des comptes rendus.

Deux gestes distincts, et l'ordre compte :

- **compresser** ne perd rien d'utile. Un WAV de réunion pèse 115 Mo par heure,
  une dizaine en Opus, et l'audio ne sert plus qu'à réécouter un passage ou à
  réenrôler une voix : la qualité d'un codec vocal y suffit. C'est donc
  automatique.
- **effacer** perd la seule pièce qu'on ne peut pas refaire. La transcription et
  le compte rendu se reconstituent depuis l'audio, l'inverse est faux. C'est
  donc désactivé par défaut, et jamais appliqué à une réunion qui n'a pas été
  transcrite.

Une voix est une donnée biométrique : pouvoir dire « les enregistrements sont
effacés au bout de N jours » est un énoncé qui a de la valeur, à condition
qu'il soit vrai. D'où une règle explicite plutôt qu'un dossier qui grossit.

Ce module ne touche à aucun fichier : il reçoit des âges et rend des décisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Geste(StrEnum):
    RIEN = "rien"
    COMPRESSER = "compresser"
    EFFACER = "effacer"


@dataclass(frozen=True, slots=True)
class Regle:
    """Les délais, en jours. Zéro désactive le geste."""

    compresser_apres: int = 7
    effacer_apres: int = 0

    def __post_init__(self) -> None:
        if self.compresser_apres < 0 or self.effacer_apres < 0:
            raise ValueError("un délai de rétention ne peut pas être négatif")
        # Effacer avant d'avoir compressé n'aurait aucun sens : le second geste
        # englobe le premier. On l'interdit plutôt que de laisser une
        # configuration qui se contredit.
        if self.effacer_apres and self.effacer_apres < self.compresser_apres:
            raise ValueError(
                "« effacer_apres » doit venir après « compresser_apres », "
                "sinon l'audio disparaît avant d'avoir été compressé"
            )

    def decider(self, jours: float, transcrite: bool, deja_compresse: bool) -> Geste:
        """Le geste dû pour une réunion de cet âge.

        Une réunion **non transcrite** n'est jamais touchée, quel que soit son
        âge : son audio est tout ce qui existe d'elle, et l'effacer reviendrait
        à effacer la réunion. Une réunion qu'on n'a pas eu le temps de traiter
        n'est pas une réunion qu'on veut perdre.
        """
        if not transcrite:
            return Geste.RIEN
        if self.effacer_apres and jours >= self.effacer_apres:
            return Geste.EFFACER
        if (self.compresser_apres and jours >= self.compresser_apres
                and not deja_compresse):
            return Geste.COMPRESSER
        return Geste.RIEN
