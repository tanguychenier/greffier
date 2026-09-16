"""What is kept of a meeting, and for how long."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Gesture(StrEnum):
    NOTHING = "rien"
    COMPRESS = "compresser"
    ERASE = "effacer"

@dataclass(frozen=True, slots=True)
class Rule:
    """The delays, in days. Zero switches the gesture off."""

    compress_after: int = 7
    erase_after: int = 0

    def __post_init__(self) -> None:
        if self.compress_after < 0 or self.erase_after < 0:
            raise ValueError("un délai de rétention ne peut pas être négatif")
        if self.erase_after and self.erase_after < self.compress_after:
            raise ValueError(
                "« effacer_apres » doit venir après « compresser_apres », "
                "sinon l'audio disparaît avant d'avoir été compressé"
            )

    def decide(self, days: float, is_transcribed: bool, already_compressed: bool) -> Gesture:
        """The gesture owed for a meeting of this age."""
        if not is_transcribed:
            return Gesture.NOTHING
        if self.erase_after and days >= self.erase_after:
            return Gesture.ERASE
        if (self.compress_after and days >= self.compress_after
                and not already_compressed):
            return Gesture.COMPRESS
        return Gesture.NOTHING
