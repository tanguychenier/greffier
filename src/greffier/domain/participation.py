"""Quand l'assistant prend la parole dans la réunion, et quand il se tait.

Un assistant vocal ordinaire répond dès que son interlocuteur se tait : c'est
juste pour un tête-à-tête, et c'est insupportable à cinq autour d'une table, où
un blanc de deux secondes n'est pas une invitation à parler mais une respiration.
Le défaut n'est pas d'ordre technique, il tient à la question posée — « a-t-on
fini de me parler ? » au lieu de « ai-je quelque chose qui vaut d'interrompre ? ».

Ce module ne pose que la seconde. Il ne sait ni écouter, ni parler, ni rédiger :
il reçoit des occasions, il en retient au plus une, et il dit pourquoi. Ce qui
permet de régler la politesse de l'outil sans lancer une réunion.

La règle tient en quatre refus :

- **ne jamais couper** : il faut un vrai creux, pas une respiration ;
- **ne pas revenir sans cesse** : une intervention spontanée, puis on se repose ;
- **ne pas se répéter** : une question posée une fois ne se repose pas ;
- **ne rien servir de froid** : une remarque sur un sujet déjà quitté est du bruit.

Être appelé par son nom échappe à tout cela : quelqu'un qui s'adresse à l'outil
attend une réponse, pas de la retenue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

CREUX_MINIMAL = 2.0

REST = 180.0

STALENESS = 90.0

DENSITE_MAXIMALE = 0.85

class Because(StrEnum):
    """Pourquoi l'assistant voudrait parler, de la plus forte à la plus faible."""

    APPELE = "on l'appelle"
    VOIX_INDISTINCTE = "il ne distingue pas une voix"
    DECISION_SANS_SUITE = "une décision sans responsable ni date"
    QUESTION_SANS_REPONSE = "une question restée en l'air"
    ECART_AVEC_UN_DOCUMENT = "un écart avec un document fourni"
    CONTRIBUTION = "il a quelque chose à ajouter"

WEIGHT = {
    Because.APPELE: 100,
    Because.VOIX_INDISTINCTE: 60,
    Because.DECISION_SANS_SUITE: 50,
    Because.QUESTION_SANS_REPONSE: 40,
    Because.ECART_AVEC_UN_DOCUMENT: 30,
    Because.CONTRIBUTION: 10,
}

@dataclass(frozen=True, slots=True)
class Opening:
    """Une chose que l'assistant pourrait dire, et ce qui la justifie."""

    because: Because
    remark: str
    born_at: float = 0.0
    subject: str = ""
    as_is: bool = False

    @property
    def weight(self) -> int:
        return WEIGHT[self.because]

    @property
    def urgent(self) -> bool:
        """Une occasion qui ignore le repos et la densité.

        Quelqu'un qui s'adresse à l'outil par son nom attend une réponse tout
        de suite ; lui opposer un budget serait absurde.
        """
        return self.because is Because.APPELE

@dataclass
class Manners:
    """Ce que l'assistant s'autorise, et la mémoire de ce qu'il a déjà dit."""

    creux_minimal: float = CREUX_MINIMAL
    rest: float = REST
    staleness: float = STALENESS
    densite_maximale: float = DENSITE_MAXIMALE
    active: bool = True
    parle_le: float | None = None
    dits: set[str] = field(default_factory=set)

    def refusal(
        self,
        opening: Opening,
        now: float,
        lull: float,
        density: float = 0.0,
    ) -> str | None:
        """Ce qui empêche de dire cette occasion, ou rien si elle peut être dite.

        Rendre la raison plutôt qu'un booléen : c'est ce qui permet de montrer
        dans la fenêtre pourquoi l'assistant s'est tu, au lieu de laisser croire
        qu'il n'avait rien à dire.
        """
        if not self.active:
            return "il ne participe pas"
        if opening.subject and opening.subject in self.dits:
            return "déjà dit"
        if opening.urgent:
            return None
        if now - opening.born_at > self.staleness:
            return "la conversation est passée à autre chose"
        if lull < self.creux_minimal:
            return "quelqu'un parle"
        if density > self.densite_maximale:
            return "la discussion est trop dense"
        if self.parle_le is not None and now - self.parle_le < self.rest:
            reste = self.rest - (now - self.parle_le)
            return f"il vient de parler, encore {reste:.0f} s de repos"
        return None

    def choose(
        self,
        occasions: list[Opening],
        now: float,
        lull: float,
        density: float = 0.0,
    ) -> Opening | None:
        """Au plus une occasion, la plus forte de celles qui passent.

        Les autres sont abandonnées et non remises à plus tard : une remarque
        gardée en réserve arrive sur un sujet que la réunion a quitté, et c'est
        exactement ce qui fait passer un participant pour distrait.
        """
        possibles = [
            o for o in occasions
            if self.refusal(o, now, lull, density) is None
        ]
        if not possibles:
            return None
        return max(possibles, key=lambda o: (o.weight, o.born_at))

    def has_spoken(self, opening: Opening, now: float) -> None:
        """À appeler une fois l'intervention réellement prononcée.

        Après coup et non avant : une synthèse vocale qui échoue ne doit pas
        coûter trois minutes de silence, ni faire croire qu'une question a été
        posée.
        """
        self.parle_le = now
        if opening.subject:
            self.dits.add(opening.subject)

def speech_density(turns: list[tuple[float, float]], now: float,
                      window: float = 60.0) -> float:
    """Part de la dernière minute où quelqu'un parlait, entre 0 et 1.

    Sert à ne pas s'insérer dans un échange serré. Se mesure sur les bornes des
    tours de parole, sans rien savoir de ce qui se dit.
    """
    depuis = max(0.0, now - window)
    width = now - depuis
    if width <= 0:
        return 0.0
    is_speaking = sum(
        max(0.0, min(end, now) - max(start, depuis))
        for start, end in turns
    )
    return min(1.0, is_speaking / width)

def _ecart_tolere(name: str) -> int:
    return 1 if len(name) < 5 else 2

def _distance(un: str, autre: str, plafond: int) -> int:
    """Distance d'édition, abandonnée dès qu'elle dépasse le plafond."""
    if abs(len(un) - len(autre)) > plafond:
        return plafond + 1
    precedent = list(range(len(autre) + 1))
    for i, lettre in enumerate(un, start=1):
        current = [i]
        for j, autre_lettre in enumerate(autre, start=1):
            current.append(min(
                precedent[j] + 1,
                current[j - 1] + 1,
                precedent[j - 1] + (lettre != autre_lettre),
            ))
        if min(current) > plafond:
            return plafond + 1
        precedent = current
    return precedent[-1]

def _strip_accents(mot: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", mot.lower())
        if unicodedata.category(c) != "Mn"
    )

def called_by_name(text: str, name: str) -> bool:
    """L'assistant est-il nommé dans cette phrase ?

    Un nom prononcé n'est pas forcément un appel — « Lucie a dit que » parle
    d'elle sans lui parler — mais la distinction est hors de portée d'une règle,
    et se taire quand on est appelé coûte bien plus cher que de répondre quand
    on ne l'était pas. C'est au propos, ensuite, de reconnaître qu'il n'y avait
    pas de question.
    """
    cherche = _strip_accents(name.strip())
    if not cherche:
        return False
    plafond = _ecart_tolere(cherche)
    words = re.findall(r"\w+", _strip_accents(text), flags=re.UNICODE)
    return any(_distance(mot, cherche, plafond) <= plafond for mot in words)

def question_asked(text: str, name: str) -> str:
    """Ce qu'on demande à l'assistant, son nom retiré.

    Le nom retiré parce qu'il n'apporte rien à la question et qu'il encombre :
    « Lucie, est-ce que tu nous entends ? » se traite mieux en « est-ce que tu
    nous entends ? ».
    """
    cherche = _strip_accents(name.strip())
    plafond = _ecart_tolere(cherche)
    gardes = [
        mot for mot in re.split(r"(\W+)", text, flags=re.UNICODE)
        if not (mot.strip() and _distance(_strip_accents(mot), cherche, plafond) <= plafond)
    ]
    reste = re.sub(r"\s+", " ", "".join(gardes))
    # « Du coup Lucie, tu peux » laisse « Du coup , tu peux » : la ponctuation
    # qui suivait le nom se retrouve détachée du mot qui la précède. Seuls la
    # virgule et le point se recollent : en français, le point-virgule, les
    # deux-points et les points d'exclamation et d'interrogation prennent une
    # espace avant, et la leur retirer serait une faute de plus, pas de moins.
    reste = re.sub(r"\s+([,.])", r"\1", reste)
    return re.sub(r"^[\s,.:;!?]+", "", reste).strip()
