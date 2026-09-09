"""Reconnaître, dans une phrase ordinaire, une demande d'apprendre quelque chose.

Alimenter le contexte demandait d'ouvrir un fichier. Dire « retiens que OTP veut
dire mot de passe à usage unique » est ce qu'on fait naturellement, et c'est ce
qu'il faut comprendre.

Le choix assumé : on reconnaît par **motifs** et non en interrogeant un modèle.
Faire analyser chaque message par le rédacteur pour savoir s'il contient une
intention coûterait un appel distant à chaque phrase tapée, y compris pour
« qu'a-t-on décidé sur Oasis ? ». Les motifs se trompent parfois — d'où la
confirmation, qui rend un faux positif inoffensif : il coûte une question, pas
une écriture.

Rien n'est jamais écrit ici. Ce module lit une phrase et rend ce qu'il croit
comprendre ; c'est l'appelant qui demande confirmation, puis qui écrit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Quoi(StrEnum):
    TERME = "terme"
    PERSONNE = "personne"


@dataclass(frozen=True, slots=True)
class Apprentissage:
    """Ce qu'une phrase demande de retenir."""

    quoi: Quoi
    #: L'écriture du terme, ou le nom de la personne.
    sujet: str
    #: Le sens du terme, ou le rôle de la personne. Peut être vide : « retiens
    #: le mot CASA » est une demande légitime, l'orthographe suffit à servir la
    #: transcription.
    precision: str = ""

    def __post_init__(self) -> None:
        if not self.sujet.strip():
            raise ValueError("un apprentissage sans sujet ne sert à rien")

    def dire(self) -> str:
        """La confirmation à poser, qui montre exactement ce qui sera écrit."""
        if self.quoi is Quoi.PERSONNE:
            qui = f"« {self.sujet} »"
            role = f", {self.precision}" if self.precision else ""
            return f"J'ajoute {qui}{role} aux personnes du contexte. Confirme ?"
        sens = f" ({self.precision})" if self.precision else ""
        return f"J'ajoute « {self.sujet} »{sens} au contexte. Confirme ?"


#: Ce qui annonce une demande d'apprendre. Le verbe d'abord : c'est lui qui
#: distingue « retiens que X est Y » d'une question ordinaire sur X.
_AMORCES = r"(?:retiens|note|apprends|souviens[- ]toi|garde)"

#: Ce qui relie un sujet à sa précision. « c'est » est exclu volontairement :
#: « OTP c'est quoi ? » est une question, pas une définition.
_LIENS = r"(?:veut dire|signifie|c'est[- ]à[- ]dire|=|:|désigne|correspond à)"

#: Un rôle de personne. Reconnaître la personne à son rôle plutôt qu'au verbe
#: évite de prendre « retiens que Maud part jeudi » pour un rôle.
_ROLES = (
    "chef", "cheffe", "responsable", "directeur", "directrice", "président",
    "présidente", "développeur", "développeuse", "architecte", "gestionnaire",
    "assistant", "assistante", "référent", "référente", "pilote", "chargé",
    "chargée", "consultant", "consultante", "ingénieur", "ingénieure",
)

#: Un motif à part pour les personnes, parce que « est » ne peut pas entrer
#: dans les liens généraux : « retiens que la réunion est annulée » n'est pas
#: une définition. Ici le rôle est **exigé** dans la précision, ce qui suffit à
#: séparer « Maud est cheffe de projet » de « la réunion est annulée ».
_MOTIF_PERSONNE = re.compile(
    rf"^\s*{_AMORCES}\b[^:]*?\bque\s+(?P<sujet>[A-ZÉÈÀÂÎÔÛ][\w'’-]{{1,30}}"
    rf"(?:\s+[A-ZÉÈÀÂÎÔÛ][\w'’-]{{1,30}})?)\s+(?:est|était|sera)\s+"
    rf"(?P<precision>.{{1,120}}?)\s*[.!]?\s*$",
    re.IGNORECASE | re.UNICODE,
)

_MOTIFS = (
    # « retiens que OTP veut dire mot de passe à usage unique »
    re.compile(
        rf"^\s*{_AMORCES}\b[^:]*?\bque\s+(?P<sujet>.{{1,60}}?)\s+{_LIENS}\s+"
        rf"(?P<precision>.{{1,160}}?)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
    # « retiens : OTP = mot de passe à usage unique »
    re.compile(
        rf"^\s*{_AMORCES}\b\s*[:,]?\s*(?P<sujet>.{{1,60}}?)\s*{_LIENS}\s*"
        rf"(?P<precision>.{{1,160}}?)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
    # « retiens le mot CASA », sans sens
    re.compile(
        rf"^\s*{_AMORCES}\b\s*(?:le mot|le terme|le sigle|l'acronyme)\s+"
        rf"(?P<sujet>.{{1,60}}?)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
)


#: Ce qui vaut « oui » et ce qui vaut « non » quand l'outil demande confirmation.
#: Ici et non dans la fenêtre : la même réponse sert à confirmer un
#: apprentissage et à répondre à une question sur un terme, et deux listes qui
#: divergent feraient accepter dans un cas ce qui est refusé dans l'autre.
ACCORDS = frozenset({
    "oui", "o", "ok", "d'accord", "daccord", "yes", "y", "exact", "exactement",
    "c'est ça", "cest ça", "c'est ca", "voilà", "voila", "tout à fait",
    "confirme", "vas-y", "va y", "parfait",
})
REFUS = frozenset({
    "non", "n", "no", "pas du tout", "annule", "laisse", "laisse tomber",
    "surtout pas", "oublie",
})


def accord(reponse: str) -> bool | None:
    """Vrai si la phrase confirme, Faux si elle refuse, None si elle fait autre chose.

    None est le cas important : une phrase qui n'est ni l'un ni l'autre est une
    nouvelle demande, pas une confirmation. La prendre pour un « non » perdrait
    la demande ; la prendre pour un « oui » écrirait sans accord.
    """
    nu = reponse.strip().casefold().rstrip(".!… ")
    if nu in ACCORDS:
        return True
    if nu in REFUS:
        return False
    return None


def comprendre(phrase: str) -> Apprentissage | None:
    """Ce que cette phrase demande de retenir, ou None si ce n'en est pas une.

    On refuse plutôt que de deviner à moitié : une phrase qui commence par un
    verbe d'apprentissage mais dont on n'extrait pas de sujet propre ne donne
    rien. Mieux vaut la traiter comme une question — l'assistant répondra — que
    d'écrire une entrée bancale dans le contexte.
    """
    personne = _MOTIF_PERSONNE.match(phrase)
    if personne is not None:
        role = _nettoyer(personne.group("precision"))
        nom = _nettoyer(personne.group("sujet"))
        # Le rôle est exigé : sans lui, « X est en congé » deviendrait une
        # entrée du contexte, ce qui n'a aucun sens et pollue l'amorce.
        if nom and _est_un_role(role):
            return Apprentissage(Quoi.PERSONNE, nom, role)

    for motif in _MOTIFS:
        trouve = motif.match(phrase)
        if trouve is None:
            continue
        sujet = _nettoyer(trouve.group("sujet"))
        precision = _nettoyer(
            trouve.groupdict().get("precision") or ""
        )
        if not sujet or len(sujet.split()) > 5:
            # Plus de cinq mots n'est pas un terme : c'est une phrase, donc on
            # a mal découpé.
            continue
        quoi = Quoi.PERSONNE if _est_un_role(precision) else Quoi.TERME
        try:
            return Apprentissage(quoi, sujet, precision)
        except ValueError:
            continue
    return None


def _nettoyer(brut: str) -> str:
    """Retire les articles et la ponctuation qui traînent autour d'un extrait."""
    nu = brut.strip().strip("\"'«»").strip()
    nu = re.sub(r"^(?:le|la|les|l'|un|une|des|du|de)\s+", "", nu, flags=re.IGNORECASE)
    return nu.strip(" .,;:!?")


def _est_un_role(precision: str) -> bool:
    """Vrai si la précision décrit une fonction plutôt qu'une définition."""
    nu = precision.casefold()
    return any(re.search(rf"\b{role}", nu) for role in _ROLES)
