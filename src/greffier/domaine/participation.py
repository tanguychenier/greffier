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

#: Un tour de parole s'enchaîne au précédent en moins d'une seconde quand la
#: discussion est vive. Deux secondes de blanc sont un creux, et non le temps
#: que quelqu'un reprenne son souffle — c'est le seuil au-delà duquel un humain
#: se permet lui-même d'entrer dans la conversation.
CREUX_MINIMAL = 2.0

#: Entre deux prises de parole spontanées. Trois minutes laissent une vingtaine
#: d'occasions sur une réunion d'une heure, là où l'outil en trouvera bien
#: davantage : c'est le budget qui fait le tri, pas la pauvreté des idées.
REPOS = 180.0

#: Passé ce délai, une occasion ne vaut plus d'être servie : la conversation est
#: ailleurs, et revenir dessus donne l'impression d'un participant distrait.
PEREMPTION = 90.0

#: Au-dessus de cette part de temps parlé sur la dernière minute, la discussion
#: est trop dense pour qu'on s'y insère sans la casser. Mesurable en direct sans
#: rien comprendre à ce qui se dit.
DENSITE_MAXIMALE = 0.85


class Raison(StrEnum):
    """Pourquoi l'assistant voudrait parler, de la plus forte à la plus faible."""

    APPELE = "on l'appelle"
    VOIX_INDISTINCTE = "il ne distingue pas une voix"
    DECISION_SANS_SUITE = "une décision sans responsable ni date"
    QUESTION_SANS_REPONSE = "une question restée en l'air"
    ECART_AVEC_UN_DOCUMENT = "un écart avec un document fourni"
    APPORT = "il a quelque chose à ajouter"


#: L'ordre de priorité, quand plusieurs occasions se présentent au même creux.
#: Être appelé passe avant tout ; ne pas savoir qui parle passe avant une idée,
#: parce que c'est le compte rendu qui en dépend et que la réponse se périme.
FORCE = {
    Raison.APPELE: 100,
    Raison.VOIX_INDISTINCTE: 60,
    Raison.DECISION_SANS_SUITE: 50,
    Raison.QUESTION_SANS_REPONSE: 40,
    Raison.ECART_AVEC_UN_DOCUMENT: 30,
    Raison.APPORT: 10,
}


@dataclass(frozen=True, slots=True)
class Occasion:
    """Une chose que l'assistant pourrait dire, et ce qui la justifie."""

    raison: Raison
    propos: str
    #: L'instant de la réunion où elle est née, en secondes.
    ne_le: float = 0.0
    #: De quoi il s'agit, pour ne pas reposer deux fois la même question. Deux
    #: occasions de même sujet sont la même : la seconde ne sera pas servie.
    sujet: str = ""
    #: Vrai quand `propos` est déjà le texte à prononcer, mot pour mot.
    #:
    #: Sans ce drapeau, un accusé de réception déjà rédigé — « je mets Hubert sur
    #: cette voix » — repassait par le modèle, qui le remplaçait par une
    #: politesse vague et perdait au passage la seule information qui comptait :
    #: le nom retenu. Une phrase écrite pour être dite n'a rien à gagner d'un
    #: aller-retour.
    tel_quel: bool = False

    @property
    def force(self) -> int:
        return FORCE[self.raison]

    @property
    def urgente(self) -> bool:
        """Une occasion qui ignore le repos et la densité.

        Quelqu'un qui s'adresse à l'outil par son nom attend une réponse tout
        de suite ; lui opposer un budget serait absurde.
        """
        return self.raison is Raison.APPELE


@dataclass
class Politique:
    """Ce que l'assistant s'autorise, et la mémoire de ce qu'il a déjà dit."""

    creux_minimal: float = CREUX_MINIMAL
    repos: float = REPOS
    peremption: float = PEREMPTION
    densite_maximale: float = DENSITE_MAXIMALE
    #: À faux, il n'ouvre plus la bouche : le bouton de la fenêtre pose ce
    #: réglage, et le repose, autant de fois qu'on veut.
    actif: bool = True
    #: Instant de la dernière prise de parole, en secondes de réunion.
    parle_le: float | None = None
    #: Les sujets déjà traités, pour ne pas y revenir.
    dits: set[str] = field(default_factory=set)

    def refus(
        self,
        occasion: Occasion,
        maintenant: float,
        creux: float,
        densite: float = 0.0,
    ) -> str | None:
        """Ce qui empêche de dire cette occasion, ou rien si elle peut être dite.

        Rendre la raison plutôt qu'un booléen : c'est ce qui permet de montrer
        dans la fenêtre pourquoi l'assistant s'est tu, au lieu de laisser croire
        qu'il n'avait rien à dire.
        """
        if not self.actif:
            return "il ne participe pas"
        if occasion.sujet and occasion.sujet in self.dits:
            return "déjà dit"
        if occasion.urgente:
            return None
        if maintenant - occasion.ne_le > self.peremption:
            return "la conversation est passée à autre chose"
        if creux < self.creux_minimal:
            return "quelqu'un parle"
        if densite > self.densite_maximale:
            return "la discussion est trop dense"
        if self.parle_le is not None and maintenant - self.parle_le < self.repos:
            reste = self.repos - (maintenant - self.parle_le)
            return f"il vient de parler, encore {reste:.0f} s de repos"
        return None

    def choisir(
        self,
        occasions: list[Occasion],
        maintenant: float,
        creux: float,
        densite: float = 0.0,
    ) -> Occasion | None:
        """Au plus une occasion, la plus forte de celles qui passent.

        Les autres sont abandonnées et non remises à plus tard : une remarque
        gardée en réserve arrive sur un sujet que la réunion a quitté, et c'est
        exactement ce qui fait passer un participant pour distrait.
        """
        possibles = [
            o for o in occasions
            if self.refus(o, maintenant, creux, densite) is None
        ]
        if not possibles:
            return None
        return max(possibles, key=lambda o: (o.force, o.ne_le))

    def a_parle(self, occasion: Occasion, maintenant: float) -> None:
        """À appeler une fois l'intervention réellement prononcée.

        Après coup et non avant : une synthèse vocale qui échoue ne doit pas
        coûter trois minutes de silence, ni faire croire qu'une question a été
        posée.
        """
        self.parle_le = maintenant
        if occasion.sujet:
            self.dits.add(occasion.sujet)


def densite_de_parole(tours: list[tuple[float, float]], maintenant: float,
                      fenetre: float = 60.0) -> float:
    """Part de la dernière minute où quelqu'un parlait, entre 0 et 1.

    Sert à ne pas s'insérer dans un échange serré. Se mesure sur les bornes des
    tours de parole, sans rien savoir de ce qui se dit.
    """
    depuis = max(0.0, maintenant - fenetre)
    largeur = maintenant - depuis
    if largeur <= 0:
        return 0.0
    parle = sum(
        max(0.0, min(fin, maintenant) - max(debut, depuis))
        for debut, fin in tours
    )
    return min(1.0, parle / largeur)


#: Ce qu'on tolère d'écart entre le nom de l'assistant et ce que la
#: transcription a entendu. « Lucie » revient en « Lucy », « Lucile », « lui
#: si » : un modèle de transcription n'a aucune raison de connaître le prénom
#: qu'on a donné à l'outil, et exiger la graphie exacte revient à ne jamais
#: répondre. Deux écarts dès cinq lettres : « Lucie » entendu « Lucy » en est à
#: deux, et c'est justement le cas courant. Le prix est un « Lucile » pris pour
#: un appel de temps à autre ; le propos répondra qu'il n'y avait pas de
#: question, ce qui coûte infiniment moins cher que de ne jamais répondre.
def _ecart_tolere(nom: str) -> int:
    return 1 if len(nom) < 5 else 2


def _distance(un: str, autre: str, plafond: int) -> int:
    """Distance d'édition, abandonnée dès qu'elle dépasse le plafond."""
    if abs(len(un) - len(autre)) > plafond:
        return plafond + 1
    precedent = list(range(len(autre) + 1))
    for i, lettre in enumerate(un, start=1):
        courant = [i]
        for j, autre_lettre in enumerate(autre, start=1):
            courant.append(min(
                precedent[j] + 1,
                courant[j - 1] + 1,
                precedent[j - 1] + (lettre != autre_lettre),
            ))
        if min(courant) > plafond:
            return plafond + 1
        precedent = courant
    return precedent[-1]


def _sans_accents(mot: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", mot.lower())
        if unicodedata.category(c) != "Mn"
    )


def appelee(texte: str, nom: str) -> bool:
    """L'assistant est-il nommé dans cette phrase ?

    Un nom prononcé n'est pas forcément un appel — « Lucie a dit que » parle
    d'elle sans lui parler — mais la distinction est hors de portée d'une règle,
    et se taire quand on est appelé coûte bien plus cher que de répondre quand
    on ne l'était pas. C'est au propos, ensuite, de reconnaître qu'il n'y avait
    pas de question.
    """
    cherche = _sans_accents(nom.strip())
    if not cherche:
        return False
    plafond = _ecart_tolere(cherche)
    mots = re.findall(r"\w+", _sans_accents(texte), flags=re.UNICODE)
    return any(_distance(mot, cherche, plafond) <= plafond for mot in mots)


def question_posee(texte: str, nom: str) -> str:
    """Ce qu'on demande à l'assistant, son nom retiré.

    Le nom retiré parce qu'il n'apporte rien à la question et qu'il encombre :
    « Lucie, est-ce que tu nous entends ? » se traite mieux en « est-ce que tu
    nous entends ? ».
    """
    cherche = _sans_accents(nom.strip())
    plafond = _ecart_tolere(cherche)
    gardes = [
        mot for mot in re.split(r"(\W+)", texte, flags=re.UNICODE)
        if not (mot.strip() and _distance(_sans_accents(mot), cherche, plafond) <= plafond)
    ]
    reste = re.sub(r"\s+", " ", "".join(gardes))
    # « Du coup Lucie, tu peux » laisse « Du coup , tu peux » : la ponctuation
    # qui suivait le nom se retrouve détachée du mot qui la précède. Seuls la
    # virgule et le point se recollent : en français, le point-virgule, les
    # deux-points et les points d'exclamation et d'interrogation prennent une
    # espace avant, et la leur retirer serait une faute de plus, pas de moins.
    reste = re.sub(r"\s+([,.])", r"\1", reste)
    return re.sub(r"^[\s,.:;!?]+", "", reste).strip()
