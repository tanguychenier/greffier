"""La carte d'un sujet : le problème, les pistes, ce qui est acté.

Une réunion de travail définit des stratégies. Cela se tient mieux en carte
qu'en prose, et cette carte se partage pour que chaque partie prenante y
contribue — « ça je l'ai fait », « ça je n'ai pas la solution ».

Trois décisions gouvernent ce module.

**Une carte par sujet, jamais par réunion.** Une réunion touche cinq sujets ; un
sujet revient sur dix réunions. Une carte par réunion produirait dix cartes
d'Oasis dont aucune ne serait à jour.

**On ajoute, on ne remplace pas.** Une carte partagée porte le travail de
plusieurs personnes. Ce qui vient d'une réunion s'ajoute à ce qui existe ; ce
qui semble dépassé se **marque**, jamais ne s'efface. Sans cette règle, une
réunion mal transcrite peut détruire le travail de dix personnes.

**Ce qui est en discussion se distingue de ce qui est acté.** La carte s'écrit
pendant la réunion, donc elle recueille des choses non tranchées. Les présenter
comme des décisions de l'équipe serait un contresens, et personne ne pourrait
plus se fier à la carte.

Ce module ne connaît aucun service : il compose et fusionne des arbres.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum


class RecorderState(StrEnum):
    """Ce que la carte affirme d'un nœud."""

    ACTE = "acté"
    EN_DISCUSSION = "en discussion"
    DEPASSE = "dépassé"

class Genre(StrEnum):
    SUBJECT = "sujet"
    PROBLEME = "problème"
    PISTE = "piste"
    ACTION = "action"
    CONSTAT = "constat"

def content_words(text: str) -> list[str]:
    """Les mots qui portent le sens, dans **l'ordre**, sans accents ni ponctuation.

    Distinct de `clef`, qui trie. Le tri est ce qu'il faut pour comparer deux
    libellés courts — « recette externalisée » et « externalisée, la recette »
    sont un seul point — mais il détruit l'adjacence, donc il ne peut pas servir
    à compter des occurrences dans un texte : « esup oasis » y apparaissait deux
    fois, une comme suite et une comme « oasis » isolé.
    """
    nu = unicodedata.normalize("NFKD", text.casefold())
    nu = "".join(lettre for lettre in nu if not unicodedata.combining(lettre))
    tous = [mot for mot in re.split(r"[^a-z0-9]+", nu) if mot]
    carriers = [mot for mot in tous if mot not in _VIDES]
    return carriers or tous

def key(text: str) -> str:
    """De quoi reconnaître deux formulations du même point.

    Sans accents, sans ponctuation, sans mots vides, et **trié** : « L'accès au
    SI » et « acces au SI » désignent la même chose, et une comparaison
    littérale créerait deux branches là où il en faut une.
    """
    carriers = content_words(text)
    return " ".join(sorted(carriers))

_VIDES = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "au", "aux",
    "et", "ou", "a", "en", "sur", "pour", "par", "avec", "sans", "dans",
    "que", "qui", "se", "ce", "cette", "il", "elle", "on", "est", "sont",
})

GENRES_DECIDABLES = frozenset({Genre.PISTE, Genre.ACTION})

SANS_ETAT = frozenset({Genre.SUBJECT})

def state_allows(kind: Genre, state: RecorderState) -> RecorderState:
    """L'état que ce genre peut porter. Ramène à « en discussion » sinon.

    « Dépassé » reste possible pour tout genre : un problème peut avoir cessé
    d'en être un.
    """
    if kind in SANS_ETAT:
        return state
    if state is RecorderState.ACTE and kind not in GENRES_DECIDABLES:
        return RecorderState.EN_DISCUSSION
    return state

PART_COMMUNE = 0.6

ECART_MOT = 2

LONGUEUR_COMPARABLE = 5

def _near_ones(un: str, autre: str) -> bool:
    """Deux mots désignent-ils la même chose, à une terminaison près."""
    if un == autre:
        return True
    if len(un) < LONGUEUR_COMPARABLE or len(autre) < LONGUEUR_COMPARABLE:
        return False
    from greffier.domain.questions import distance

    return distance(un, autre) <= ECART_MOT

def same_point(un: str, autre: str) -> bool:
    """Vrai si ces deux libellés désignent le même point de la carte.

    La comparaison exacte des clefs ne suffisait pas : le rédacteur reformule
    d'une extraction à l'autre, et chaque reformulation ouvrait une branche de
    plus — un quart des points revenaient en doublon, mesuré. On compare donc la
    **part de mots porteurs communs**, en rapprochant les mots à une terminaison
    près.

    Le sens est symétrique et la part se calcule sur le plus court des deux :
    « la recette » et « la recette d'Oasis bloquée faute d'environnement » ne
    sont pas le même point, et diviser par l'union le dirait à tort dès que l'un
    est un fragment de l'autre.
    """
    mots_un, mots_autre = set(content_words(un)), set(content_words(autre))
    if not mots_un or not mots_autre:
        return False
    if mots_un == mots_autre:
        return True
    communs = sum(
        1 for mot in mots_un if any(_near_ones(mot, target) for target in mots_autre)
    )
    return communs / max(len(mots_un), len(mots_autre)) >= PART_COMMUNE

@dataclass
class Noeud:
    """Un point de la carte, et ce qui s'y rattache."""

    text: str
    kind: Genre = Genre.CONSTAT
    state: RecorderState = RecorderState.EN_DISCUSSION

    def __post_init__(self) -> None:
        self.state = state_allows(self.kind, self.state)
    enfants: list[Noeud] = field(default_factory=list)
    meetings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return key(self.text)

    def enfant(self, text: str) -> Noeud | None:
        """L'enfant qui porte ce point, à la reformulation près."""
        return next((n for n in self.enfants if same_point(n.text, text)), None)

    def count(self) -> int:
        """Nombre de nœuds, celui-ci compris."""
        return 1 + sum(enfant.count() for enfant in self.enfants)

@dataclass
class Carte:
    """La carte d'un sujet, telle qu'elle existe à un instant."""

    subject: str
    racine: Noeud | None = None

    def __post_init__(self) -> None:
        if self.racine is None:
            self.racine = Noeud(self.subject, kind=Genre.SUBJECT, state=RecorderState.ACTE)

    @property
    def count(self) -> int:
        return self.racine.count() if self.racine else 0

@dataclass(frozen=True, slots=True)
class Apport:
    """Ce qu'une réunion apporte : un point, et où l'accrocher.

    `sous` est le texte du parent, pas un identifiant : ce qui vient d'une
    transcription ne connaît aucun identifiant, et retrouver le parent par son
    libellé est précisément le travail de `clef`.
    """

    text: str
    kind: Genre = Genre.CONSTAT
    state: RecorderState = RecorderState.EN_DISCUSSION
    sous: str = ""

@dataclass(frozen=True, slots=True)
class Bilan:
    """Ce qu'une fusion a changé. Rien n'est jamais supprimé."""

    ajoutes: tuple[str, ...] = ()
    actes: tuple[str, ...] = ()
    known: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.ajoutes and not self.actes

def join(board: Carte, apports: list[Apport], meeting: str = "") -> Bilan:
    """Verse les apports dans la carte. **N'efface rien, jamais.**

    Un apport dont le parent est introuvable se raccroche à la racine plutôt que
    d'être perdu : mal placé, il reste corrigeable d'un glissement de souris ;
    perdu, il faut réécouter la réunion.
    """
    assert board.racine is not None
    ajoutes: list[str] = []
    actes: list[str] = []
    known: list[str] = []

    for contribution in apports:
        if not contribution.text.strip():
            continue
        parent = _find(board.racine, contribution.sous) if contribution.sous else board.racine
        if parent is None:
            parent = board.racine
        existant = parent.enfant(contribution.text)
        if existant is None:
            parent.enfants.append(Noeud(
                text=contribution.text.strip(),
                kind=contribution.kind,
                state=contribution.state,
                meetings=[meeting] if meeting else [],
            ))
            ajoutes.append(contribution.text.strip())
            continue
        if meeting and meeting not in existant.meetings:
            existant.meetings.append(meeting)
        voulu = state_allows(existant.kind, contribution.state)
        if voulu is RecorderState.ACTE and existant.state is RecorderState.EN_DISCUSSION:
            existant.state = RecorderState.ACTE
            actes.append(existant.text)
        else:
            known.append(existant.text)

    return Bilan(tuple(ajoutes), tuple(actes), tuple(known))

def _find(noeud: Noeud, text: str) -> Noeud | None:
    """Le nœud portant ce libellé, où qu'il soit dans l'arbre."""
    if same_point(noeud.text, text):
        return noeud
    for enfant in noeud.enfants:
        trouve = _find(enfant, text)
        if trouve is not None:
            return trouve
    return None

def mark_overdue(board: Carte, text: str) -> bool:
    """Marque un point comme dépassé. Le nœud reste dans la carte.

    Le garder a un intérêt propre : une piste écartée qu'on efface revient à la
    réunion suivante, et le groupe refait le même chemin.
    """
    assert board.racine is not None
    trouve = _find(board.racine, text)
    if trouve is None or trouve is board.racine:
        return False
    trouve.state = RecorderState.DEPASSE
    return True
