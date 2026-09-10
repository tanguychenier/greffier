"""Juger si un niveau de parole suffit à transcrire.

Le contrôle qui existait mesurait le **silence** : il sert à repérer un micro
coupé, et c'est utile, mais un micro qui capte -49 dB de bruit de pièce ne dit
rien de ce que donnera la parole. Or c'est la parole qui décide.

Les seuils viennent de deux mesures faites sur ce projet, pas d'un usage :

- à **-43 dB** de parole, le modèle a rendu « Merci d'avoir regardé cette
  vidéo ! » là où la personne disait « Test, test de réunion ». Un signal faible
  ne donne pas une transcription pauvre, il en donne une **inventée**, ce qui est
  bien pire : elle traverse le compte rendu avec le même aplomb que le reste.
- en dessous de **-70 dB**, il n'y a rien du tout : c'est le seuil que la chaîne
  de traitement emploie déjà pour refuser un enregistrement muet.

Entre les deux, la transcription se dégrade sans qu'on puisse dire où elle
basculera. D'où trois verdicts et non deux : « faible » avertit sans bloquer,
parce qu'une réunion qui a lieu vaut mieux qu'une réunion refusée pour un
décibel.
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

def juger(db: float) -> Verdict:
    """Ce que vaut ce niveau de parole."""
    if db < MUET_DB:
        return Verdict.MUET
    if db < INSUFFISANT_DB:
        return Verdict.INSUFFISANT
    if db < BON_DB:
        return Verdict.FAIBLE
    return Verdict.BON

def dire(db: float) -> str:
    """Une phrase pour l'écran, qui dit le niveau **et** quoi en faire."""
    verdict = juger(db)
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

def suffisant(db: float) -> bool:
    """Vrai si on peut démarrer sans avertir."""
    return juger(db) in (Verdict.BON, Verdict.FAIBLE)

RELEVES_AVANT_ALERTE = 8

@dataclass
class SurveillanceDeNiveau:
    """Suit le niveau capté pendant la réunion et dit s'il ne suffit pas.

    Le **maximum** et non la moyenne : entre deux phrases il y a du silence, et
    une moyenne sur une réunion mesure surtout les silences. Ce qui compte est
    de savoir si la parole, quand elle a lieu, arrive assez fort.

    Alerte **une seule fois**. Le niveau ne se corrige pas en cours de réunion
    sans interrompre, donc répéter n'ajoute rien : on le dit, la personne fait
    ce qu'elle veut, et le compte rendu le saura de toute façon par
    l'avertissement de couverture.
    """

    releves: int = 0
    meilleur_db: float = -200.0
    alertee: bool = False

    def constater(self, db: float) -> str:
        """Rend ce qu'il faut signaler, ou une chaîne vide."""
        self.releves += 1
        self.meilleur_db = max(self.meilleur_db, db)
        if self.alertee or self.releves < RELEVES_AVANT_ALERTE:
            return ""
        if suffisant(self.meilleur_db):
            return ""
        self.alertee = True
        return (
            f"Le son capté reste trop faible ({self.meilleur_db:.0f} dB au plus "
            "haut depuis le début). " + dire(self.meilleur_db)
        )
