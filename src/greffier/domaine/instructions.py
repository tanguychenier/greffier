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

from greffier.domaine.modeles import Replique


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

# Formulations qui annoncent une décision ou une suite à donner. Elles servent à
# faire remonter les points à retenir pendant la réunion, pas à décider.
_DECISIONS = [
    re.compile(r"(?i:\bon (?:décide|acte|valide|part sur|retient)\b)"),
    re.compile(r"(?i:\bil faut (?:qu[e']|absolument)\b)"),
    re.compile(r"(?i:\bje (?:m'en charge|prends|note)\b)"),
    re.compile(r"(?i:\b(?:action|à faire|suite à donner)\s*:)"),
    re.compile(r"(?i:\bd'ici (?:lundi|mardi|mercredi|jeudi|vendredi|la semaine|le)\b)"),
]


@dataclass(frozen=True, slots=True)
class Proposition:
    """Quelque chose à faire, soumis à validation."""

    genre: Genre
    texte: str
    instant: float
    origine: Origine
    contexte: str = ""

    @property
    def clef(self) -> str:
        """De quoi reconnaître un doublon.

        Le presse-papier est relu en boucle : sans cela, un lien copié une fois
        serait proposé à chaque tour.
        """
        return f"{self.genre}:{self.texte.strip().lower()}"


def liens_dans(texte: str) -> list[str]:
    """Adresses présentes dans un texte, sans doublon et dans l'ordre."""
    vus: list[str] = []
    for trouve in _LIEN.finditer(texte):
        # La ponctuation finale colle souvent à l'adresse quand elle est
        # recopiée depuis une phrase.
        lien = trouve.group(0).rstrip(".,;:!?")
        if lien not in vus:
            vus.append(lien)
    return vus


def instruction_apres(texte: str, mot_cle: str) -> str | None:
    """Ce qui suit le mot d'activation, s'il est prononcé.

    On coupe à la fin de la phrase : au-delà, la personne est passée à autre
    chose et l'instruction se noierait dans la suite de la réunion.
    """
    motif = re.compile(rf"(?i:\b{re.escape(mot_cle)}\b)[\s,:—-]*(?P<suite>[^.?!]{{3,240}})")
    trouve = motif.search(texte)
    if not trouve:
        return None
    suite = trouve.group("suite").strip()
    return suite or None


def decisions_dans(texte: str) -> bool:
    """Le passage annonce-t-il une décision ou une suite à donner ?"""
    return any(motif.search(texte) for motif in _DECISIONS)


@dataclass
class Veille:
    """Accumule les propositions d'une réunion, sans jamais rien répéter."""

    mot_cle: str = "greffier"
    propositions: list[Proposition] = field(default_factory=list)
    _vues: set[str] = field(default_factory=set)

    def _ajouter(self, proposition: Proposition) -> bool:
        if proposition.clef in self._vues:
            return False
        self._vues.add(proposition.clef)
        self.propositions.append(proposition)
        return True

    def ecouter(self, repliques: list[Replique]) -> list[Proposition]:
        """Relève ce qui, dans la parole, appelle une action."""
        nouvelles: list[Proposition] = []
        for replique in repliques:
            instant = replique.intervalle.debut
            instruction = instruction_apres(replique.texte, self.mot_cle)
            if instruction:
                candidate = Proposition(
                    genre=Genre.INSTRUCTION, texte=instruction, instant=instant,
                    origine=Origine.PAROLE, contexte=replique.texte.strip(),
                )
                if self._ajouter(candidate):
                    nouvelles.append(candidate)
                # Une instruction explicite suffit : inutile de la reclasser
                # aussi en décision.
                continue
            if decisions_dans(replique.texte):
                candidate = Proposition(
                    genre=Genre.DECISION, texte=replique.texte.strip(), instant=instant,
                    origine=Origine.PAROLE, contexte="",
                )
                if self._ajouter(candidate):
                    nouvelles.append(candidate)
        return nouvelles

    def coller(self, contenu: str, instant: float) -> list[Proposition]:
        """Relève les liens passés par le presse-papier.

        C'est la source fiable : le texte est exact, il n'a pas transité par la
        transcription.
        """
        nouvelles: list[Proposition] = []
        for lien in liens_dans(contenu):
            candidate = Proposition(
                genre=Genre.LIEN, texte=lien, instant=instant,
                origine=Origine.PRESSE_PAPIER,
            )
            if self._ajouter(candidate):
                nouvelles.append(candidate)
        return nouvelles

    def par_genre(self, genre: Genre) -> list[Proposition]:
        return [p for p in self.propositions if p.genre is genre]
