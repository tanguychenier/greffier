"""Reconnaître de quel sujet une réunion parle, et retrouver sa carte.

C'est la difficulté réelle, plus que d'écrire la carte. Une réunion ne parle pas
d'un sujet, elle en parle de cinq — celle du 2026-09-09 a touché un projet, une
recette, un environnement, des questionnaires et l'accompagnement d'une
personne. Et le même sujet se nomme de dix façons d'une fois à l'autre :
« Oasis », « esup-oasis », « le projet Oasis ». Une comparaison littérale échoue
dès la deuxième formulation, et chaque échec crée une carte de plus.

D'où un **registre** : le sujet porte ses appellations, et c'est un humain qui
les y met. On ne devine pas qu'« esup-oasis » et « Oasis » sont le même projet ;
on l'apprend une fois. Ce que la machine fait bien, en revanche, c'est compter
les occurrences et dire « ce sujet a été abordé longuement » plutôt que « il a
été mentionné une fois ».

Un sujet mentionné une seule fois n'est **pas** un sujet de la réunion : c'est
une allusion. Écrire une carte pour chaque allusion la remplirait de bruit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from greffier.domaine.carte import clef, mots_porteurs

MENTIONS_MINIMALES = 3

@dataclass(frozen=True, slots=True)
class Sujet:
    """Un sujet suivi, ses appellations, et où vit sa carte."""

    nom: str
    alias: tuple[str, ...] = ()
    carte: str = ""

    def __post_init__(self) -> None:
        if not self.nom.strip():
            raise ValueError("un sujet sans nom ne se retrouve pas")

    @property
    def appellations(self) -> tuple[str, ...]:
        return (self.nom, *self.alias)

    def reconnait(self, mot: str) -> bool:
        """Vrai si ce mot est une de ses appellations."""
        return clef(mot) in {clef(nom) for nom in self.appellations}

@dataclass
class Registre:
    """Les sujets suivis, et ce qu'une transcription en dit."""

    sujets: list[Sujet] = field(default_factory=list)

    def par_nom(self, nom: str) -> Sujet | None:
        return next((sujet for sujet in self.sujets if sujet.reconnait(nom)), None)

    def compter(self, texte: str) -> dict[str, int]:
        """Combien de fois chaque sujet suivi est nommé dans ce texte.

        Compte **toutes** ses appellations ensemble : c'est tout l'intérêt du
        registre. Le comptage est insensible à la casse et aux accents, sur des
        mots entiers — « prod » ne doit pas se compter dans « production ».
        """
        # Dans l'ordre du texte, sans tri : compter une suite de mots suppose
        # que l'adjacence soit préservée.
        mots = mots_porteurs(texte)
        present: dict[str, int] = {}
        for sujet in self.sujets:
            total = _compter_sans_chevauchement(mots, sujet.appellations)
            if total:
                present[sujet.nom] = total
        return present

    def sujets_de(self, texte: str, minimum: int = MENTIONS_MINIMALES) -> list[str]:
        """Les sujets réellement traités, du plus présent au moins présent.

        Sous le seuil, on considère qu'il s'agit d'une allusion : ouvrir une
        carte pour chacune la remplirait de bruit.
        """
        comptes = self.compter(texte)
        retenus = [(nom, compte) for nom, compte in comptes.items() if compte >= minimum]
        return [nom for nom, _ in sorted(retenus, key=lambda paire: -paire[1])]

def _compter_sans_chevauchement(
    mots: list[str], appellations: tuple[str, ...]
) -> int:
    """Combien de fois ce sujet est nommé, sans compter deux fois le même mot.

    Additionner les occurrences de chaque appellation comptait double : dans
    « puis d'esup-oasis », la suite « esup oasis » **et** le mot « oasis »
    qu'elle contient étaient tous deux relevés, et « Oasis » mentionné trois
    fois en devenait quatre. Une seule passe, les appellations les plus longues
    essayées d'abord, et on avance de ce qui a été consommé.
    """
    suites = sorted(
        (mots_porteurs(appellation) for appellation in appellations),
        key=len, reverse=True,
    )
    suites = [suite for suite in suites if suite]
    if not suites:
        return 0
    total = 0
    position = 0
    while position < len(mots):
        trouvee = next(
            (suite for suite in suites
             if mots[position:position + len(suite)] == suite),
            None,
        )
        if trouvee is None:
            position += 1
            continue
        total += 1
        position += len(trouvee)
    return total
