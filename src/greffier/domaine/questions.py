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

#: La distance tolérée dépend de la longueur du terme, parce qu'une distance
#: absolue confond des mots courants avec des termes métier. Mesuré sur le
#: vocabulaire réel du poste : « point » et « sprint » sont à 2, et rien ne les
#: rapproche — demander « fallait-il comprendre sprint ? » chaque fois que
#: quelqu'un dit « point » ferait fermer la file au bout d'une minute. À partir
#: de huit lettres, deux écarts restent une déformation plausible.
#:
#: La distance employée compte la **transposition** pour un seul écart : les
#: erreurs de transcription inversent des lettres — « bakclog » pour
#: « backlog » — et deux mots à une transposition près sont le même mot.
LONGUEUR_TOLERANCE_LARGE = 8
DISTANCE_MAXIMUM = 2

#: En dessous, la distance ne veut rien dire : « CR » et « OR » sont à 1 et
#: n'ont aucun rapport. Les sigles courts sont justement ceux qu'on écrit en
#: majuscules, donc reconnaissables autrement.
LONGUEUR_MINIMALE = 5


def tolerance(terme: str) -> int:
    """Combien d'écarts on accepte avant de croire à une déformation."""
    return DISTANCE_MAXIMUM if len(terme) >= LONGUEUR_TOLERANCE_LARGE else 1

#: Une même question ne se pose pas deux fois dans une réunion, et l'outil ne
#: doit pas noyer qui travaille. Au-delà, il se taît et garde le reste pour la
#: transcription définitive, qui a le contexte complet.
QUESTIONS_MAXIMUM = 8

_MOT = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)


class Motif(StrEnum):
    """Pourquoi l'outil demande. Dit à l'écran : une question sans raison
    visible ressemble à un caprice, et on n'y répond pas."""

    TERME_PROCHE = "terme-proche"


@dataclass(frozen=True, slots=True)
class Question:
    numero: int
    #: La question, telle qu'elle s'affiche.
    texte: str
    motif: Motif
    #: Ce qui l'a déclenchée : le mot entendu et le terme soupçonné.
    entendu: str = ""
    attendu: str = ""

    @property
    def clef(self) -> str:
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
    avant_precedente: list[int] = []
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
                cout = min(cout, avant_precedente[j - 2] + 1)
            courante.append(cout)
        avant_precedente, precedente = precedente, courante
    return precedente[-1]


def _mots(texte: str) -> list[str]:
    return _MOT.findall(texte)


@dataclass
class Interrogateur:
    """Repère ce qui mérite une question, sans jamais reposer la même.

    Tient la mémoire des questions déjà posées : le fil du direct répète les
    mêmes mots pendant toute la réunion, et redemander à chaque occurrence
    rendrait la file inutilisable.
    """

    #: Les écritures que le contexte connaît. Comparées en minuscules.
    connus: tuple[str, ...] = ()
    posees: set[str] = field(default_factory=set)
    _numero: int = 0

    def __post_init__(self) -> None:
        # Les termes composés sont aussi indexés mot par mot : le fil se compare
        # mot à mot, donc « mrege » ne rencontrait jamais « merge request » et
        # passait inaperçu. Les mots trop courts sont écartés au même titre que
        # les sigles.
        eclates: list[str] = []
        for terme in self.connus:
            eclates.append(terme)
            morceaux = _mots(terme)
            if len(morceaux) > 1:
                eclates.extend(m for m in morceaux if len(m) >= LONGUEUR_MINIMALE)
        vus: dict[str, str] = {}
        for terme in eclates:
            vus.setdefault(terme.casefold(), terme)
        self.connus = tuple(vus.values())

    def examiner(self, texte: str) -> list[Question]:
        """Les questions que ce passage soulève. Vide la plupart du temps."""
        if len(self.posees) >= QUESTIONS_MAXIMUM:
            return []
        trouvees: list[Question] = []
        for mot in _mots(texte):
            if len(mot) < LONGUEUR_MINIMALE:
                continue
            nu = mot.casefold()
            candidat = self._terme_proche(nu)
            if candidat is None:
                continue
            question = Question(
                numero=self._numero + 1,
                texte=(
                    f"J'ai entendu « {mot} ». Fallait-il comprendre "
                    f"« {candidat} » ?"
                ),
                motif=Motif.TERME_PROCHE,
                entendu=mot,
                attendu=candidat,
            )
            if question.clef in self.posees:
                continue
            self.posees.add(question.clef)
            self._numero += 1
            trouvees.append(question)
            if len(self.posees) >= QUESTIONS_MAXIMUM:
                break
        return trouvees

    def _terme_proche(self, mot_nu: str) -> str | None:
        """Le terme connu dont ce mot est probablement une déformation.

        Le mot **exactement** connu ne déclenche rien : c'est le cas normal, et
        de loin le plus fréquent.
        """
        meilleur: tuple[int, str] | None = None
        for terme in self.connus:
            terme_nu = terme.casefold()
            if terme_nu == mot_nu:
                return None
            if len(terme) < LONGUEUR_MINIMALE:
                continue
            ecart = distance(mot_nu, terme_nu)
            if ecart <= tolerance(terme) and (meilleur is None or ecart < meilleur[0]):
                meilleur = (ecart, terme)
        return meilleur[1] if meilleur else None
