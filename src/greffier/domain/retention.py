"""What is kept of a meeting, and for how long."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Gesture(StrEnum):
    RIEN = "rien"
    COMPRESSER = "compresser"
    EFFACER = "effacer"

@dataclass(frozen=True, slots=True)
class Rule:
    """The delays, in days. Zero switches the gesture off."""

    compresser_apres: int = 7
    effacer_apres: int = 0

    def __post_init__(self) -> None:
        if self.compresser_apres < 0 or self.effacer_apres < 0:
            raise ValueError("un délai de rétention ne peut pas être négatif")
        if self.effacer_apres and self.effacer_apres < self.compresser_apres:
            raise ValueError(
                "« effacer_apres » doit venir après « compresser_apres », "
                "sinon l'audio disparaît avant d'avoir été compressé"
            )

    def decide(self, jours: float, transcrite: bool, deja_compresse: bool) -> Gesture:
        """The gesture owed for a meeting of this age."""
        if not transcrite:
            return Gesture.RIEN
        if self.effacer_apres and jours >= self.effacer_apres:
            return Gesture.EFFACER
        if (self.compresser_apres and jours >= self.compresser_apres
                and not deja_compresse):
            return Gesture.COMPRESSER
        return Gesture.RIEN
