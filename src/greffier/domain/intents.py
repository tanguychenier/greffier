"""Recognising, in an ordinary sentence, a request to remember something."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class What(StrEnum):
    TERME = "terme"
    NOBODY = "personne"

@dataclass(frozen=True, slots=True)
class Learning:
    """What a sentence asks to be remembered."""

    what: What
    subject: str
    precision: str = ""

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("un apprentissage sans sujet ne sert à rien")

    def say(self) -> str:
        """The confirmation to show, spelling out exactly what will be written."""
        if self.what is What.NOBODY:
            who = f"« {self.subject} »"
            role = f", {self.precision}" if self.precision else ""
            return f"J'ajoute {who}{role} aux personnes du contexte. Confirme ?"
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

_PERSON_PATTERN = re.compile(
    rf"^\s*{_AMORCES}\b[^:]*?\bque\s+(?P<sujet>[A-ZÉÈÀÂÎÔÛ][\w'’-]{{1,30}}"
    rf"(?:\s+[A-ZÉÈÀÂÎÔÛ][\w'’-]{{1,30}})?)\s+(?:est|était|sera)\s+"
    rf"(?P<precision>.{{1,120}}?)\s*[.!]?\s*$",
    re.IGNORECASE | re.UNICODE,
)

_MOTIFS = (
    re.compile(
        rf"^\s*{_AMORCES}\b[^:]*?\bque\s+(?P<sujet>.{{1,60}}?)\s+{_LIENS}\s+"
        rf"(?P<precision>.{{1,160}}?)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*{_AMORCES}\b\s*[:,]?\s*(?P<sujet>.{{1,60}}?)\s*{_LIENS}\s*"
        rf"(?P<precision>.{{1,160}}?)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
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
    """True when the sentence confirms, False when it refuses, None otherwise."""
    nu = response.strip().casefold().rstrip(".!… ")
    if nu in ACCORDS:
        return True
    if nu in REFUSAL:
        return False
    return None

def understand(sentence: str) -> Learning | None:
    """What this sentence asks to remember, or None if it asks nothing."""
    person = _PERSON_PATTERN.match(sentence)
    if person is not None:
        role = _clean(person.group("precision"))
        name = _clean(person.group("sujet"))
        if name and _is_a_role(role):
            return Learning(What.NOBODY, name, role)

    for motif in _MOTIFS:
        found = motif.match(sentence)
        if found is None:
            continue
        subject = _clean(found.group("sujet"))
        precision = _clean(
            found.groupdict().get("precision") or ""
        )
        if not subject or len(subject.split()) > 5:
            continue
        what = What.NOBODY if _is_a_role(precision) else What.TERME
        try:
            return Learning(what, subject, precision)
        except ValueError:
            continue
    return None

def _clean(brut: str) -> str:
    """Removes the articles and punctuation left around a term."""
    nu = brut.strip().strip("\"'«»").strip()
    nu = re.sub(r"^(?:le|la|les|l'|un|une|des|du|de)\s+", "", nu, flags=re.IGNORECASE)
    return nu.strip(" .,;:!?")

def _is_a_role(precision: str) -> bool:
    """True when the detail describes a role rather than a definition."""
    nu = precision.casefold()
    return any(re.search(rf"\b{role}", nu) for role in _ROLES)
