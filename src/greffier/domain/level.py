"""Judging whether a speech level is enough to transcribe.

A weak signal does not give a poor transcript: it gives an **invented** one.
Measured at -43 dB, whisper returned "thanks for watching this video" where the
person said "test, meeting test".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

BON_DB = -30.0

INSUFFISANT_DB = -43.0

class Verdict(StrEnum):
    BON = "bon"
    FAIBLE = "faible"
    INSUFFISANT = "insuffisant"
    MUET = "muet"

MUET_DB = -70.0

def judge(db: float) -> Verdict:
    """What this speech level is worth."""
    if db < MUET_DB:
        return Verdict.MUET
    if db < INSUFFISANT_DB:
        return Verdict.INSUFFISANT
    if db < BON_DB:
        return Verdict.FAIBLE
    return Verdict.BON

def say(db: float) -> str:
    """A sentence for the screen, giving the level **and** what to do about it."""
    verdict = judge(db)
    if verdict is Verdict.MUET:
        return (
            f"Rien n'est capté ({db:.0f} dB). Vérifie le bouton de sourdine du "
            "casque, le micro choisi, puis l'autorisation micro dans les "
            "réglages du système."
        )
    if verdict is Verdict.INSUFFISANT:
        return (
            f"Trop faible pour transcrire ({db:.0f} dB). À ce niveau, le modèle "
            "n'écrit pas moins bien : il invente. Rapproche le micro, monte son "
            "gain, ou prends un casque avant de démarrer."
        )
    if verdict is Verdict.FAIBLE:
        return (
            f"Faible ({db:.0f} dB). La réunion sera transcrite, mais des mots "
            "seront perdus ou déformés. Un casque porté suffit généralement à "
            "gagner vingt décibels."
        )
    return f"Bon niveau ({db:.0f} dB)."

def sufficient(db: float) -> bool:
    """True when recording can start without a warning."""
    return judge(db) in (Verdict.BON, Verdict.FAIBLE)

RELEVES_AVANT_ALERTE = 8

@dataclass
class LevelWatch:
    """Follows the captured level during the meeting and says if it falls short."""

    releves: int = 0
    meilleur_db: float = -200.0
    alertee: bool = False

    def observe(self, db: float) -> str:
        """What needs reporting, or an empty string."""
        self.releves += 1
        self.meilleur_db = max(self.meilleur_db, db)
        if self.alertee or self.releves < RELEVES_AVANT_ALERTE:
            return ""
        if sufficient(self.meilleur_db):
            return ""
        self.alertee = True
        return (
            f"Le son capté reste trop faible ({self.meilleur_db:.0f} dB au plus "
            "haut depuis le début). " + say(self.meilleur_db)
        )
