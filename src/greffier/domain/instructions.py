"""Repérer, pendant la réunion, ce qui appelle une action.

Deux sources, et elles n'ont pas la même fiabilité :

- **le presse-papier** — quand quelqu'un colle un lien dans le chat, le texte
  est exact. C'est de loin la source la plus sûre.
- **la parole** — après un mot d'activation, la phrase qui suit est prise pour
  une instruction. Utile, mais transcrite, donc faillible.

Un lien *dicté à l'oral* n'est presque jamais transcrit correctement — « miro
point com slash board slash b n 7 x » ne donnera pas une adresse valable. On ne
prétend donc pas en extraire : ce qui est repéré dans la parole, ce sont des
intentions, pas des adresses.

Rien n'est exécuté ici. Ce module produit des propositions ; c'est un humain qui
déclenche. Une action lancée seule sur une phrase mal transcrite, au milieu
d'une réunion confidentielle, se retourne vite contre son auteur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from greffier.domain.language import LanguageProfile
from greffier.domain.models import Utterance
from greffier.domain.profiles.neutral import NEUTRAL


class Origine(StrEnum):
    PAROLE = "parole"
    PRESSE_PAPIER = "presse_papier"

class Genre(StrEnum):
    INSTRUCTION = "instruction"   # « Greffier, ouvre le ticket… »
    LIEN = "lien"                 # une adresse collée
    DECISION = "decision"         # « on décide de… », « il faut que… »

# Adresses http(s) et chemins de dépôt collés. Volontairement strict : mieux
# vaut rater un lien exotique que proposer d'ouvrir n'importe quoi.
_LIEN = re.compile(r"https?://[^\s<>\"'()\[\]]{4,}")

@dataclass(frozen=True, slots=True)
class Proposition:
    """Quelque chose à faire, soumis à validation."""

    kind: Genre
    text: str
    at_instant: float
    origine: Origine
    context: str = ""

    @property
    def key(self) -> str:
        """De quoi reconnaître un doublon.

        Le presse-papier est relu en boucle : sans cela, un lien copié une fois
        serait proposé à chaque tour.
        """
        return f"{self.kind}:{self.text.strip().lower()}"

def liens_dans(text: str) -> list[str]:
    """Adresses présentes dans un texte, sans doublon et dans l'ordre."""
    vus: list[str] = []
    for trouve in _LIEN.finditer(text):
        # La ponctuation finale colle souvent à l'adresse quand elle est
        # recopiée depuis une phrase.
        lien = trouve.group(0).rstrip(".,;:!?")
        if lien not in vus:
            vus.append(lien)
    return vus

def instruction_after(text: str, mot_cle: str) -> str | None:
    """Ce qui suit le mot d'activation, s'il est prononcé.

    On coupe à la fin de la phrase : au-delà, la personne est passée à autre
    chose et l'instruction se noierait dans la suite de la réunion.
    """
    motif = re.compile(rf"(?i:\b{re.escape(mot_cle)}\b)[\s,:—-]*(?P<suite>[^.?!]{{3,240}})")
    trouve = motif.search(text)
    if not trouve:
        return None
    suite = trouve.group("suite").strip()
    return suite or None

def decisions_in(text: str, profil: LanguageProfile) -> bool:
    """Le passage annonce-t-il une décision ou une suite à donner ?

    Les tournures appartiennent à la langue. Une langue sans tournures relevées
    n'en trouve aucune : la veille se tait plutôt que de proposer au hasard.
    """
    return any(motif.search(text) for motif in profil.redaction.motifs_de_decision)

@dataclass
class WatchRules:
    """Accumule les propositions d'une réunion, sans jamais rien répéter."""

    mot_cle: str = "greffier"
    profil: LanguageProfile = NEUTRAL
    propositions: list[Proposition] = field(default_factory=list)
    _vues: set[str] = field(default_factory=set)

    def _add(self, proposition: Proposition) -> bool:
        if proposition.key in self._vues:
            return False
        self._vues.add(proposition.key)
        self.propositions.append(proposition)
        return True

    def listen(self, utterances: list[Utterance]) -> list[Proposition]:
        """Relève ce qui, dans la parole, appelle une action."""
        nouvelles: list[Proposition] = []
        for utterance in utterances:
            at_instant = utterance.span.start
            instruction = instruction_after(utterance.text, self.mot_cle)
            if instruction:
                candidate = Proposition(
                    kind=Genre.INSTRUCTION, text=instruction, at_instant=at_instant,
                    origine=Origine.PAROLE, context=utterance.text.strip(),
                )
                if self._add(candidate):
                    nouvelles.append(candidate)
                # Une instruction explicite suffit : inutile de la reclasser
                # aussi en décision.
                continue
            if decisions_in(utterance.text, self.profil):
                candidate = Proposition(
                    kind=Genre.DECISION, text=utterance.text.strip(), at_instant=at_instant,
                    origine=Origine.PAROLE, context="",
                )
                if self._add(candidate):
                    nouvelles.append(candidate)
        return nouvelles

    def paste(self, content: str, at_instant: float) -> list[Proposition]:
        """Relève les liens passés par le presse-papier.

        C'est la source fiable : le texte est exact, il n'a pas transité par la
        transcription.
        """
        nouvelles: list[Proposition] = []
        for lien in liens_dans(content):
            candidate = Proposition(
                kind=Genre.LIEN, text=lien, at_instant=at_instant,
                origine=Origine.PRESSE_PAPIER,
            )
            if self._add(candidate):
                nouvelles.append(candidate)
        return nouvelles

    def by_gender(self, kind: Genre) -> list[Proposition]:
        return [p for p in self.propositions if p.kind is kind]
