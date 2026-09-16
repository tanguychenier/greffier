"""Judging whether a speech level is enough to transcribe.

A weak signal does not give a poor transcript: it gives an **invented** one.
Measured at -43 dB, whisper returned "thanks for watching this video" where the
person said "test, meeting test".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

GOOD_DB = -30.0

INSUFFICIENT_DB = -43.0

class Verdict(StrEnum):
    GOOD = "bon"
    WEAK = "faible"
    INSUFFICIENT = "insuffisant"
    SILENT = "muet"

SILENT_DB = -70.0

def judge(db: float) -> Verdict:
    """What this speech level is worth."""
    if db < SILENT_DB:
        return Verdict.SILENT
    if db < INSUFFICIENT_DB:
        return Verdict.INSUFFICIENT
    if db < GOOD_DB:
        return Verdict.WEAK
    return Verdict.GOOD

def say(db: float) -> str:
    """A sentence for the screen, giving the level **and** what to do about it."""
    verdict = judge(db)
    if verdict is Verdict.SILENT:
        return (
            f"Rien n'est capté ({db:.0f} dB). Vérifie le bouton de sourdine du "
            "casque, le micro choisi, puis l'autorisation micro dans les "
            "réglages du système."
        )
    if verdict is Verdict.INSUFFICIENT:
        return (
            f"Trop faible pour transcrire ({db:.0f} dB). À ce niveau, le modèle "
            "n'écrit pas moins bien : il invente. Rapproche le micro, monte son "
            "gain, ou prends un casque avant de démarrer."
        )
    if verdict is Verdict.WEAK:
        return (
            f"Faible ({db:.0f} dB). La réunion sera transcrite, mais des mots "
            "seront perdus ou déformés. Un casque porté suffit généralement à "
            "gagner vingt décibels."
        )
    return f"Bon niveau ({db:.0f} dB)."

def sufficient(db: float) -> bool:
    """True when recording can start without a warning."""
    return judge(db) in (Verdict.GOOD, Verdict.WEAK)

READINGS_BEFORE_ALERT = 8

@dataclass
class LevelWatch:
    """Follows the captured level during the meeting and says if it falls short."""

    readings_: int = 0
    best_db: float = -200.0
    alerted: bool = False

    def observe(self, db: float) -> str:
        """What needs reporting, or an empty string."""
        self.readings_ += 1
        self.best_db = max(self.best_db, db)
        if self.alerted or self.readings_ < READINGS_BEFORE_ALERT:
            return ""
        if sufficient(self.best_db):
            return ""
        self.alerted = True
        return (
            f"Le son capté reste trop faible ({self.best_db:.0f} dB au plus "
            "haut depuis le début). " + say(self.best_db)
        )
