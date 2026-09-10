"""Ce que l'outil ne comprend pas et sur quoi il a le droit de demander.

Un modèle de transcription ne rend jamais « je n'ai pas compris » : il rend le
mot le plus proche qu'il connaît, avec le même aplomb que pour le reste. C'est
ce qui rend une erreur coûteuse — « Ouasis » a l'air d'un mot, il traverse le
compte rendu, et personne ne voit qu'il fallait lire « Oasis ».

Le signal retenu est celui qui ne produit presque pas de faux positifs : un mot
du fil **très proche** d'un terme que le contexte connaît, sans être ce terme.
Une distance de un ou deux sur « Oasis » ne se rencontre pas par hasard dans une
réunion qui parle d'Oasis. Un mot simplement inconnu, lui, n'est pas un signal :
une réunion en contient des dizaines, tous légitimes, et demander pour chacun
ferait fuir.

Une question n'interrompt personne : elle attend dans une file, l'onglet en
porte le compte, et on y répond quand on veut — pendant la réunion ou après.
Répondre alimente le contexte, donc la réunion suivante n'a plus à demander.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

LONGUEUR_TOLERANCE_LARGE = 8
DISTANCE_MAXIMUM = 2

LONGUEUR_MINIMALE = 5

def tolerance(terme: str) -> int:
    """Combien d'écarts on accepte avant de croire à une déformation."""
    return DISTANCE_MAXIMUM if len(terme) >= LONGUEUR_TOLERANCE_LARGE else 1

QUESTIONS_MAXIMUM = 8

OCCURRENCES_QUI_ETABLISSENT = 2

_MOT = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)

_PLURIEL = re.compile(r"(?:s|x)$")

def canonical_form(mot: str) -> str:
    """Ce qu'il reste d'un mot quand on retire ce qui ne le change pas.

    Deux mots de même forme canonique sont le même mot : il n'y a rien à
    demander. On ne s'en sert **que** pour se taire, jamais pour identifier —
    la réduction est trop grossière pour ça, et confondrait « bu » et « bus ».
    """
    import unicodedata

    depouille = unicodedata.normalize("NFD", mot.casefold())
    without_accents = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    sans_liaison = re.sub(r"[-'’\s]", "", without_accents)
    return _PLURIEL.sub("", sans_liaison)

def same_word(un: str, autre: str) -> bool:
    """Les deux ne diffèrent-ils que par le pluriel, l'accent ou la casse ?"""
    return canonical_form(un) == canonical_form(autre)

PREFIXES = ("re", "ré", "de", "dé", "in", "im", "non", "anti", "pre", "pré",
            "sur", "sous", "mal", "co")

def derived_word(mot: str, terme: str) -> bool:
    """Le mot est-il le terme précédé d'un préfixe français ?

    On compare sur les formes canoniques, et l'**élision** compte : « ré- »
    devant une voyelle donne « rétablissement » et non « réétablissement ». Sans
    elle, le cas qui a motivé cette règle passait au travers.
    """
    court, long = canonical_form(terme), canonical_form(mot)
    if len(long) <= len(court) or not court:
        return False
    for prefixe in (canonical_form(p) for p in PREFIXES):
        if not long.startswith(prefixe):
            continue
        reste = long[len(prefixe):]
        # Sans élision, puis avec : le terme peut avoir perdu sa voyelle
        # initiale au contact du préfixe.
        if reste == court or (court[0] in "aeiouy" and reste == court[1:]):
            return True
    return False

class Motif(StrEnum):
    """Pourquoi l'outil demande. Dit à l'écran : une question sans raison
    visible ressemble à un caprice, et on n'y répond pas."""

    NEAR_TERM = "terme-proche"

@dataclass(frozen=True, slots=True)
class Question:
    number: int
    text: str
    motif: Motif
    entendu: str = ""
    attendu: str = ""

    @property
    def key(self) -> str:
        """De quoi reconnaître une question déjà posée, sans dépendre du texte."""
        return f"{self.motif}:{self.entendu.casefold()}:{self.attendu.casefold()}"

def distance(un: str, autre: str) -> int:
    """Distance d'édition **avec transposition** (Damerau-Levenshtein).

    La transposition compte pour un seul écart, et c'est le point : une
    transcription inverse des lettres, « bakclog » pour « backlog ». Sans elle,
    ces deux mots sont à 2, au même rang que « point » et « sprint » qui n'ont
    rien à voir — donc le seuil ne pouvait pas séparer les deux cas.

    Écrite ici plutôt qu'empruntée : c'est vingt lignes, et une dépendance de
    plus dans le domaine se paierait à chaque installation.
    """
    if un == autre:
        return 0
    if abs(len(un) - len(autre)) > DISTANCE_MAXIMUM:
        return DISTANCE_MAXIMUM + 1
    # Trois lignes suffisent parce qu'une transposition ne regarde qu'une ligne
    # de plus en arrière.
    before_previous: list[int] = []
    precedente = list(range(len(autre) + 1))
    for i, lettre_un in enumerate(un, start=1):
        courante = [i]
        for j, lettre_autre in enumerate(autre, start=1):
            cout = min(
                precedente[j] + 1,
                courante[j - 1] + 1,
                precedente[j - 1] + (lettre_un != lettre_autre),
            )
            if (
                i > 1 and j > 1
                and lettre_un == autre[j - 2]
                and un[i - 2] == lettre_autre
            ):
                cout = min(cout, before_previous[j - 2] + 1)
            courante.append(cout)
        before_previous, precedente = precedente, courante
    return precedente[-1]

def _words(text: str) -> list[str]:
    return _MOT.findall(text)

@dataclass
class Questioner:
    """Repère ce qui mérite une question, sans jamais reposer la même.

    Tient la mémoire des questions déjà posées : le fil du direct répète les
    mêmes mots pendant toute la réunion, et redemander à chaque occurrence
    rendrait la file inutilisable.
    """

    known: tuple[str, ...] = ()
    posees: set[str] = field(default_factory=set)
    _entendus: dict[str, int] = field(default_factory=dict, repr=False)
    _number: int = 0

    def __post_init__(self) -> None:
        # Les termes composés sont aussi indexés mot par mot : le fil se compare
        # mot à mot, donc « mrege » ne rencontrait jamais « merge request » et
        # passait inaperçu. Les mots trop courts sont écartés au même titre que
        # les sigles.
        eclates: list[str] = []
        for terme in self.known:
            eclates.append(terme)
            chunks = _words(terme)
            if len(chunks) > 1:
                eclates.extend(m for m in chunks if len(m) >= LONGUEUR_MINIMALE)
        vus: dict[str, str] = {}
        for terme in eclates:
            vus.setdefault(terme.casefold(), terme)
        self.known = tuple(vus.values())

    def examine(self, text: str) -> list[Question]:
        """Les questions que ce passage soulève. Vide la plupart du temps."""
        # Compter d'abord, juger ensuite : c'est le nombre d'occurrences qui
        # dit si un mot est voulu, et le mot en cours compte pour une.
        self._retenir(text)
        if len(self.posees) >= QUESTIONS_MAXIMUM:
            return []
        trouvees: list[Question] = []
        for mot in _words(text):
            if len(mot) < LONGUEUR_MINIMALE:
                continue
            nu = mot.casefold()
            candidat = self._near_term(nu)
            if candidat is None:
                continue
            if self._established(nu) or self._already_said_right(candidat):
                continue
            question = Question(
                number=self._number + 1,
                text=(
                    f"J'ai entendu « {mot} ». Fallait-il comprendre "
                    f"« {candidat} » ?"
                ),
                motif=Motif.NEAR_TERM,
                entendu=mot,
                attendu=candidat,
            )
            if question.key in self.posees:
                continue
            self.posees.add(question.key)
            self._number += 1
            trouvees.append(question)
            if len(self.posees) >= QUESTIONS_MAXIMUM:
                break
        return trouvees

    def _retenir(self, text: str) -> None:
        """Compte ce qui a été entendu, avant de juger quoi que ce soit."""
        for mot in _words(text):
            if len(mot) < LONGUEUR_MINIMALE:
                continue
            key = canonical_form(mot)
            self._entendus[key] = self._entendus.get(key, 0) + 1

    def _established(self, mot_nu: str) -> bool:
        """Ce mot revient-il assez pour être un mot voulu ?

        Une déformation ne se répète pas à l'identique : le modèle rend
        « s'enature » une fois, pas trois. Un mot français revient, et c'est ce
        qui sépare « marge », qui est un mot, de « merve », qui n'en est pas un.
        """
        return self._entendus.get(canonical_form(mot_nu), 0) >= (
            OCCURRENCES_QUI_ETABLISSENT)

    def _already_said_right(self, terme: str) -> bool:
        """Le terme attendu a-t-il déjà été transcrit correctement ?

        Si « merge » a été rendu comme tel ailleurs dans la réunion, alors
        « merde » est probablement bien « merde » : le modèle sait écrire le
        terme, il n'a pas eu besoin de le déformer ici.
        """
        return canonical_form(terme) in self._entendus

    def _near_term(self, mot_nu: str) -> str | None:
        """Le terme connu dont ce mot est probablement une déformation.

        Le mot **exactement** connu ne déclenche rien : c'est le cas normal, et
        de loin le plus fréquent.
        """
        best: tuple[int, str] | None = None
        for terme in self.known:
            terme_nu = terme.casefold()
            # Le mot connu, à un pluriel ou un accent près, est le mot connu.
            # Demander « fallait-il comprendre "bailleur" ? » à quelqu'un qui a
            # dit « bailleurs » ne corrige rien et fait fermer la file.
            if terme_nu == mot_nu or same_word(mot_nu, terme_nu):
                return None
            # « rétablissement » n'est pas « établissement » mal entendu : c'est
            # un autre mot, et un mot du français.
            if derived_word(mot_nu, terme_nu):
                return None
            if len(terme) < LONGUEUR_MINIMALE:
                continue
            gap = distance(mot_nu, terme_nu)
            if gap <= tolerance(terme) and (best is None or gap < best[0]):
                best = (gap, terme)
        return best[1] if best else None
