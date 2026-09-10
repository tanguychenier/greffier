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
    subject: str
    precision: str = ""

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("un apprentissage sans sujet ne sert à rien")

    def say(self) -> str:
        """La confirmation à poser, qui montre exactement ce qui sera écrit."""
        if self.quoi is Quoi.PERSONNE:
            qui = f"« {self.subject} »"
            role = f", {self.precision}" if self.precision else ""
            return f"J'ajoute {qui}{role} aux personnes du contexte. Confirme ?"
        sens = f" ({self.precision})" if self.precision else ""
        return f"J'ajoute « {self.subject} »{sens} au contexte. Confirme ?"

_AMORCES = r"(?:retiens|note|apprends|souviens[- ]toi|garde)"

_LIENS = r"(?:veut dire|signifie|c'est[- ]à[- ]dire|=|:|désigne|correspond à)"

_ROLES = (
    "chef", "cheffe", "responsable", "directeur", "directrice", "président",
    "présidente", "développeur", "développeuse", "architecte", "gestionnaire",
    "assistant", "assistante", "référent", "référente", "pilote", "chargé",
    "chargée", "consultant", "consultante", "ingénieur", "ingénieure",
)

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

ACCORDS = frozenset({
    "oui", "o", "ok", "d'accord", "daccord", "yes", "y", "exact", "exactement",
    "c'est ça", "cest ça", "c'est ca", "voilà", "voila", "tout à fait",
    "confirme", "vas-y", "va y", "parfait",
})
REFUSAL = frozenset({
    "non", "n", "no", "pas du tout", "annule", "laisse", "laisse tomber",
    "surtout pas", "oublie",
})

def agreement(response: str) -> bool | None:
    """Vrai si la phrase confirme, Faux si elle refuse, None si elle fait autre chose.

    None est le cas important : une phrase qui n'est ni l'un ni l'autre est une
    nouvelle demande, pas une confirmation. La prendre pour un « non » perdrait
    la demande ; la prendre pour un « oui » écrirait sans accord.
    """
    nu = response.strip().casefold().rstrip(".!… ")
    if nu in ACCORDS:
        return True
    if nu in REFUSAL:
        return False
    return None

def understand(phrase: str) -> Apprentissage | None:
    """Ce que cette phrase demande de retenir, ou None si ce n'en est pas une.

    On refuse plutôt que de deviner à moitié : une phrase qui commence par un
    verbe d'apprentissage mais dont on n'extrait pas de sujet propre ne donne
    rien. Mieux vaut la traiter comme une question — l'assistant répondra — que
    d'écrire une entrée bancale dans le contexte.
    """
    personne = _MOTIF_PERSONNE.match(phrase)
    if personne is not None:
        role = _clean(personne.group("precision"))
        name = _clean(personne.group("sujet"))
        # Le rôle est exigé : sans lui, « X est en congé » deviendrait une
        # entrée du contexte, ce qui n'a aucun sens et pollue l'amorce.
        if name and _is_a_role(role):
            return Apprentissage(Quoi.PERSONNE, name, role)

    for motif in _MOTIFS:
        trouve = motif.match(phrase)
        if trouve is None:
            continue
        subject = _clean(trouve.group("sujet"))
        precision = _clean(
            trouve.groupdict().get("precision") or ""
        )
        if not subject or len(subject.split()) > 5:
            # Plus de cinq mots n'est pas un terme : c'est une phrase, donc on
            # a mal découpé.
            continue
        quoi = Quoi.PERSONNE if _is_a_role(precision) else Quoi.TERME
        try:
            return Apprentissage(quoi, subject, precision)
        except ValueError:
            continue
    return None

def _clean(brut: str) -> str:
    """Retire les articles et la ponctuation qui traînent autour d'un extrait."""
    nu = brut.strip().strip("\"'«»").strip()
    nu = re.sub(r"^(?:le|la|les|l'|un|une|des|du|de)\s+", "", nu, flags=re.IGNORECASE)
    return nu.strip(" .,;:!?")

def _is_a_role(precision: str) -> bool:
    """Vrai si la précision décrit une fonction plutôt qu'une définition."""
    nu = precision.casefold()
    return any(re.search(rf"\b{role}", nu) for role in _ROLES)
