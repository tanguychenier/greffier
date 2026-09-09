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


class Etat(StrEnum):
    """Ce que la carte affirme d'un nœud."""

    #: Le groupe l'a arrêté. Seule une décision explicite le mérite.
    ACTE = "acté"
    #: Évoqué, pas tranché. L'état par défaut de tout ce qui vient du direct.
    EN_DISCUSSION = "en discussion"
    #: Quelqu'un l'a marqué comme dépassé. Le nœud **reste** : la carte garde
    #: la trace de ce qui a été envisagé, ce qui évite d'y revenir en boucle.
    DEPASSE = "dépassé"


class Genre(StrEnum):
    #: La racine : le sujet lui-même. Ni décidé ni en discussion — il **est**.
    #: Sans ce genre, la règle qui interdit d'acter un problème dégradait la
    #: racine en « en discussion », si bien que la carte d'Oasis annonçait
    #: qu'Oasis était en discussion.
    SUJET = "sujet"
    PROBLEME = "problème"
    PISTE = "piste"
    ACTION = "action"
    CONSTAT = "constat"


def mots_porteurs(texte: str) -> list[str]:
    """Les mots qui portent le sens, dans **l'ordre**, sans accents ni ponctuation.

    Distinct de `clef`, qui trie. Le tri est ce qu'il faut pour comparer deux
    libellés courts — « recette externalisée » et « externalisée, la recette »
    sont un seul point — mais il détruit l'adjacence, donc il ne peut pas servir
    à compter des occurrences dans un texte : « esup oasis » y apparaissait deux
    fois, une comme suite et une comme « oasis » isolé.
    """
    nu = unicodedata.normalize("NFKD", texte.casefold())
    nu = "".join(lettre for lettre in nu if not unicodedata.combining(lettre))
    tous = [mot for mot in re.split(r"[^a-z0-9]+", nu) if mot]
    porteurs = [mot for mot in tous if mot not in _VIDES]
    return porteurs or tous


def clef(texte: str) -> str:
    """De quoi reconnaître deux formulations du même point.

    Sans accents, sans ponctuation, sans mots vides, et **trié** : « L'accès au
    SI » et « acces au SI » désignent la même chose, et une comparaison
    littérale créerait deux branches là où il en faut une.
    """
    porteurs = mots_porteurs(texte)
    # Un libellé fait **uniquement** de mots vides garderait une clef vide, et
    # tous ces libellés se confondraient : « A » et « D » sont deux mots vides
    # français, donc deux branches distinctes n'en auraient plus fait qu'une, la
    # seconde écrasant silencieusement la première. Fusionner à tort est le
    # défaut le plus coûteux ici — on perd de l'information au lieu d'en
    # dupliquer. `mots_porteurs` garde donc tous les mots dans ce cas.
    return " ".join(sorted(porteurs))


#: Mots qui ne portent pas le sens et dont la présence varie d'une formulation à
#: l'autre. Volontairement court : une liste longue rapprocherait des points
#: distincts, ce qui est le défaut le plus coûteux ici.
_VIDES = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "au", "aux",
    "et", "ou", "a", "en", "sur", "pour", "par", "avec", "sans", "dans",
    "que", "qui", "se", "ce", "cette", "il", "elle", "on", "est", "sont",
})


#: Les genres pour lesquels « acté » veut dire quelque chose. Une piste peut
#: être retenue, une action décidée. Un **problème** est constaté, pas décidé :
#: le marquer « acté » n'a pas de sens et le lecteur y lit « le groupe a tranché
#: là-dessus », ce qui est faux. Mesuré sur une extraction réelle du
#: 2026-09-09 : sept problèmes sur douze revenaient marqués « acté », le
#: rédacteur ayant lu « acté » comme « établi ».
GENRES_DECIDABLES = frozenset({Genre.PISTE, Genre.ACTION})

#: Les genres qui ne portent pas d'état lisible. La racine en est.
SANS_ETAT = frozenset({Genre.SUJET})


def etat_possible(genre: Genre, etat: Etat) -> Etat:
    """L'état que ce genre peut porter. Ramène à « en discussion » sinon.

    « Dépassé » reste possible pour tout genre : un problème peut avoir cessé
    d'en être un.
    """
    if genre in SANS_ETAT:
        return etat
    if etat is Etat.ACTE and genre not in GENRES_DECIDABLES:
        return Etat.EN_DISCUSSION
    return etat


@dataclass
class Noeud:
    """Un point de la carte, et ce qui s'y rattache."""

    texte: str
    genre: Genre = Genre.CONSTAT
    etat: Etat = Etat.EN_DISCUSSION

    def __post_init__(self) -> None:
        self.etat = etat_possible(self.genre, self.etat)
    enfants: list[Noeud] = field(default_factory=list)
    #: Réunions qui ont parlé de ce point. Sert à dire d'où vient une branche,
    #: ce qui est la première question de qui découvre une carte.
    reunions: list[str] = field(default_factory=list)

    @property
    def clef(self) -> str:
        return clef(self.texte)

    def enfant(self, texte: str) -> Noeud | None:
        cherchee = clef(texte)
        return next((n for n in self.enfants if n.clef == cherchee), None)

    def compte(self) -> int:
        """Nombre de nœuds, celui-ci compris."""
        return 1 + sum(enfant.compte() for enfant in self.enfants)


@dataclass
class Carte:
    """La carte d'un sujet, telle qu'elle existe à un instant."""

    sujet: str
    racine: Noeud | None = None

    def __post_init__(self) -> None:
        if self.racine is None:
            self.racine = Noeud(self.sujet, genre=Genre.SUJET, etat=Etat.ACTE)

    @property
    def compte(self) -> int:
        return self.racine.compte() if self.racine else 0


@dataclass(frozen=True, slots=True)
class Apport:
    """Ce qu'une réunion apporte : un point, et où l'accrocher.

    `sous` est le texte du parent, pas un identifiant : ce qui vient d'une
    transcription ne connaît aucun identifiant, et retrouver le parent par son
    libellé est précisément le travail de `clef`.
    """

    texte: str
    genre: Genre = Genre.CONSTAT
    etat: Etat = Etat.EN_DISCUSSION
    sous: str = ""


@dataclass(frozen=True, slots=True)
class Bilan:
    """Ce qu'une fusion a changé. Rien n'est jamais supprimé."""

    ajoutes: tuple[str, ...] = ()
    #: Points déjà présents dont l'état a été relevé — « en discussion » devenu
    #: « acté ». L'inverse n'a pas lieu : une décision prise ne se dé-décide pas
    #: parce qu'une réunion suivante en reparle.
    actes: tuple[str, ...] = ()
    #: Points déjà présents et inchangés. Comptés pour pouvoir dire « rien de
    #: neuf sur ce sujet » plutôt que de republier une carte identique.
    connus: tuple[str, ...] = ()

    @property
    def vide(self) -> bool:
        return not self.ajoutes and not self.actes


def fusionner(carte: Carte, apports: list[Apport], reunion: str = "") -> Bilan:
    """Verse les apports dans la carte. **N'efface rien, jamais.**

    Un apport dont le parent est introuvable se raccroche à la racine plutôt que
    d'être perdu : mal placé, il reste corrigeable d'un glissement de souris ;
    perdu, il faut réécouter la réunion.
    """
    assert carte.racine is not None
    ajoutes: list[str] = []
    actes: list[str] = []
    connus: list[str] = []

    for apport in apports:
        if not apport.texte.strip():
            continue
        parent = _trouver(carte.racine, apport.sous) if apport.sous else carte.racine
        if parent is None:
            parent = carte.racine
        existant = parent.enfant(apport.texte)
        if existant is None:
            parent.enfants.append(Noeud(
                texte=apport.texte.strip(),
                genre=apport.genre,
                etat=apport.etat,
                reunions=[reunion] if reunion else [],
            ))
            ajoutes.append(apport.texte.strip())
            continue
        if reunion and reunion not in existant.reunions:
            existant.reunions.append(reunion)
        # Une décision relève l'état ; elle ne l'abaisse pas. « Acté » qui
        # redeviendrait « en discussion » ferait douter de toute la carte.
        voulu = etat_possible(existant.genre, apport.etat)
        if voulu is Etat.ACTE and existant.etat is Etat.EN_DISCUSSION:
            existant.etat = Etat.ACTE
            actes.append(existant.texte)
        else:
            connus.append(existant.texte)

    return Bilan(tuple(ajoutes), tuple(actes), tuple(connus))


def _trouver(noeud: Noeud, texte: str) -> Noeud | None:
    """Le nœud portant ce libellé, où qu'il soit dans l'arbre."""
    cherchee = clef(texte)
    if noeud.clef == cherchee:
        return noeud
    for enfant in noeud.enfants:
        trouve = _trouver(enfant, texte)
        if trouve is not None:
            return trouve
    return None


def marquer_depasse(carte: Carte, texte: str) -> bool:
    """Marque un point comme dépassé. Le nœud reste dans la carte.

    Le garder a un intérêt propre : une piste écartée qu'on efface revient à la
    réunion suivante, et le groupe refait le même chemin.
    """
    assert carte.racine is not None
    trouve = _trouver(carte.racine, texte)
    if trouve is None or trouve is carte.racine:
        return False
    trouve.etat = Etat.DEPASSE
    return True
