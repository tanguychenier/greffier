"""Le fil de la réunion, pendant qu'elle a lieu.

Ce que la chaîne complète fait après coup — découper, regrouper les voix,
reconnaître les personnes — se refait ici tranche par tranche, avec beaucoup
moins de matière : quelques secondes d'audio au lieu d'une heure, une empreinte
au lieu de huit. Les conclusions sont donc plus fragiles, et c'est le point
central de ce module : **il propose, il n'affirme pas**, et il garde trace de ce
qui distingue une certitude d'une hypothèse.

Trois sources de savoir, de la plus fiable à la moins :

1. **la correction humaine.** Quelqu'un a dit qui parlait ; plus rien ne
   discute. C'est l'objet même de ce module : rendre corrigeable pendant la
   réunion ce qui, sinon, ne se découvre faux qu'en relisant le compte rendu.
2. **le canal.** Une voix qui arrive par le micro est celle de la personne qui
   enregistre. Fait de câblage, pas déduction acoustique — voir `canaux`.
3. **l'empreinte vocale.** Utile, jamais sûre : le seuil de 0,70 mesuré sur des
   tours de parole entiers (`docs/calibrage.md`) s'applique ici à des extraits
   de quelques secondes, donc avec moins de marge.

Rien ici ne connaît whisper, sherpa, ni un fichier : le fil reçoit des répliques
et des empreintes, et rend des tours attribués. C'est ce qui permet de tester
l'attribution en direct, et les corrections, sans audio et sans modèle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from greffier.domaine.canaux import VOIX_LOCALE
from greffier.domaine.empreintes import (
    MATIERE_ETABLIE,
    SEUIL_ADOPTION,
    agreger,
    fusionner_voix,
    reconnaitre,
    similarite,
)
from greffier.domaine.generiques import est_un_generique, est_une_annotation
from greffier.domaine.langue import ProfilLinguistique
from greffier.domaine.modeles import Empreinte, Intervalle, Personne, Replique
from greffier.domaine.profils.neutre import NEUTRE
from greffier.domaine.questions import distance

#: Matière minimale pour **fonder** une voix. En deçà, une bribe rejoint la voix
#: la plus ressemblante plutôt que d'inventer une personne. Mesuré sur une
#: réunion en présentiel : les voix qui portaient réellement la réunion sont
#: nées sur 3,0 à 7,3 s de parole, les voix parasites sur 1,0 et 1,5 s. Trente
#: des cent soixante phrases duraient moins d'une seconde et demie.
#:
#: Rien à voir avec le seuil de ressemblance : une bribe peut ressembler
#: fortement à la mauvaise personne, c'est sa brièveté qui la rend suspecte.
MATIERE_MINIMALE_VOIX = 2.0

#: Matière exigée avant de laisser la banque de voix nommer quelqu'un.
#:
#: Reconnaître demande davantage que rattacher. Mesuré en séance : sur une
#: réunion de trente-deux minutes, la banque a collé « Kilian ? » sur une voix de
#: trois tours et « Florent ? » sur une de quatre, alors que ni l'un ni l'autre
#: n'était là. Quelques secondes de parole ressemblent à trop de monde, et une
#: étiquette fausse affichée à l'écran est pire qu'un « Voix 12 » : on la croit.
#:
#: Six secondes, soit le double du seuil du calibrage sous lequel un extrait
#: porte le bruit de la pièce plus que le timbre. En deçà, la voix reste
#: anonyme et `_retenter_le_nom` repassera : une voix qui compte finit toujours
#: par accumuler de la matière.
MATIERE_POUR_RECONNAITRE = 6.0

#: Écart exigé avec la deuxième voix établie, pour qu'une phrase la rejoigne.
#:
#: Non nul, contrairement au recollage d'après réunion, et pour une raison qui
#: tient au moment : après coup, on compare des **agrégats** de plusieurs
#: minutes, et se tromper ne coûte qu'un « greffier revoir ». Ici on compare une
#: phrase, souvent brève, et l'attribution s'affiche tout de suite sous les yeux
#: des participants. Une marge écarte les cas où deux voix se disputent la
#: phrase à égalité — ceux-là méritent le fourre-tout plutôt qu'un choix
#: arbitraire, qu'un clic devrait ensuite défaire.
MARGE_ADOPTION_DIRECT = 0.06

#: Seuil de rattachement d'une phrase à une voix déjà entendue, **en direct**.
#:
#: Bien plus bas que `SEUIL_FUSION`, et c'est une mesure qui l'impose. Le
#: rattachement compare une empreinte de deux ou trois secondes à l'agrégat
#: d'une voix, ce qui n'est pas la même question que comparer deux agrégats
#: après la réunion. Mille neuf cent dix empreintes courtes d'une réunion réelle,
#: étiquetées par le recollage final :
#:
#:   phrase / agrégat, même personne     médiane 0,667   1er décile 0,494
#:   phrase / agrégat, personnes ≠       médiane 0,337   9e décile  0,501
#:
#: À 0,75, la médiane d'une même personne ne passait pas : chaque phrase fondait
#: une voix, et comme aucune voix ne grossissait, aucune ne pouvait plus en
#: adopter. Mesuré : **deux cent soixante-seize voix pour mille phrases**, un
#: cercle vicieux entier.
#:
#: 0,50 tombe entre les deux distributions, qui ne se chevauchent qu'au décile.
#: C'est la marge qui rend ce chevauchement sans conséquence : il ne suffit pas
#: qu'une voix passe le seuil, il faut qu'elle devance nettement la suivante.
SEUIL_RATTACHEMENT_DIRECT = 0.50

#: Au-delà de ce nombre de voix, une phrase en rejoint une plutôt que d'en
#: fonder une de plus.
#:
#: C'est le plafond qui manquait, et son absence était structurelle : chaque
#: phrase qui ne ressemblait à rien fondait une voix, donc aucune voix ne
#: grossissait, donc aucune n'avait d'agrégat assez fiable pour en accueillir
#: une autre. Mesuré sur une réunion réelle de trois personnes : **deux cent
#: soixante-seize voix pour mille phrases**, et le coût de chaque rattachement
#: croissant avec elles.
#:
#: Douze parce qu'une réunion de travail dépasse rarement ce nombre, et que le
#: plafond n'a pas à être juste : il a à borner le désastre. Le nombre annoncé
#: dans la configuration, quand il l'est, l'emporte et vaut bien mieux.
VOIX_AU_PLUS = 12

#: Nom affiché pour la personne qui enregistre. Son micro la désigne : elle n'a
#: pas à être reconnue, et son nom n'a pas à être demandé.
NOM_LOCAL = "Toi"

#: Voix des passages distants dont l'extrait est trop court pour porter une
#: empreinte — un « oui », un « d'accord ». Ils sont **regroupés** sous une
#: étiquette qui ne prétend rien, plutôt que de créer un participant par bribe :
#: sans cela, une heure de réunion afficherait des dizaines de fausses voix.
VOIX_INDETERMINEE = "?"
NOM_INDETERMINE = "Les autres"

#: Part de sa durée qu'une réplique doit apporter de neuf pour être affichée.
#: Les tranches se recouvrent volontairement, donc chaque passage est transcrit
#: deux fois — mais **jamais découpé au même endroit** : mesuré, la même phrase
#: est datée 13,60 dans une tranche et 12,80 dans la suivante. Filtrer sur le
#: seul début jetait alors une phrase entière parce qu'elle commençait 0,3 s
#: avant la frontière. On compare donc ce qu'elle apporte, pas où elle commence.
PART_NEUVE_MINIMALE = 0.5

#: En deçà, un cumul d'extraits ne vaut pas d'être versé à la banque de voix.
#: Trois secondes : c'est le seuil du calibrage (`docs/calibrage.md`), sous
#: lequel un extrait porte le bruit de la pièce plus que le timbre, et celui
#: retenu après la réunion (`nommer.DUREE_UTILE`). Exiger davantage paraissait
#: prudent et coûtait tout : à l'essai, une correction saisie à la deuxième
#: phrase n'entrait jamais en banque, donc ne servait ni à la réunion suivante
#: ni au compte rendu.
DUREE_POUR_LA_BANQUE_S = 3.0

#: En deçà, un recouvrement d'un seul mot banal (« et », « de ») ne doit rien
#: couper : ce serait le hasard, pas une vraie répétition.
CARACTERES_RECOUVREMENT_MINIMUM = 4

#: À partir de combien de mots on accepte un recouvrement **imparfait**. En
#: dessous, seule l'égalité mot pour mot coupe : sur un ou deux mots, deux
#: phrases différentes se ressemblent trop souvent.
MOTS_POUR_TOLERER = 3

#: Part des mots qui doivent être identiques, les autres devant être de simples
#: variantes du même mot. Relevé le 2026-09-09 dans une réunion réelle :
#: « Qu'est-ce qu'on dit d'autre sur l'ASIS ? » puis « - Qu'est-ce qu'on dit
#: d'autre sur Oasis ? Il y a cette histoire… » — six mots sur sept identiques,
#: et la phrase s'affichait deux fois faute de coupe. Chaque doublon coûtait en
#: plus une empreinte, donc une voix de plus dans le fil.
PART_IDENTIQUE = 0.5

_MOT_DIRECT = re.compile(r"\S+")
_PONCTUATION_MOT = ".,;:!?…\"'«»()[]-–—"


def _mots_porteurs(texte: str) -> list[tuple[str, int]]:
    """Les mots qui portent du sens, chacun avec sa fin dans le texte.

    La ponctuation seule est écartée : le modèle préfixe une réplique d'un
    tiret de dialogue, et comparer « - » à « Qu'est-ce » faisait échouer la
    comparaison au premier mot, donc ne coupait rien du tout.
    """
    trouves: list[tuple[str, int]] = []
    for mot in _MOT_DIRECT.finditer(texte):
        nu = mot.group().strip(_PONCTUATION_MOT).casefold()
        if nu:
            trouves.append((nu, mot.end()))
    return trouves


def _meme_mot(un: str, autre: str) -> bool:
    """Deux transcriptions du même mot : « l'ASIS » et « Oasis ».

    Le seuil dépend de la longueur, comme pour les questions : sur trois
    lettres, deux écarts font un autre mot.
    """
    if un == autre:
        return True
    plus_court = min(len(un), len(autre))
    if plus_court < 4:
        return False
    return distance(un, autre) <= (2 if plus_court >= 5 else 1)


def _se_recouvrent(gauche: list[str], droite: list[str]) -> bool:
    """Vrai si ces deux suites de mots sont le même passage, dit deux fois."""
    if gauche == droite:
        return True
    if len(gauche) < MOTS_POUR_TOLERER:
        return False
    # Tous les mots doivent au moins être des variantes l'un de l'autre : sans
    # cela, « on va faire ça » et « on va faire autrement » se recouvriraient
    # sur trois mots et la phrase neuve disparaîtrait.
    if not all(_meme_mot(a, b) for a, b in zip(gauche, droite, strict=True)):
        return False
    identiques = sum(1 for a, b in zip(gauche, droite, strict=True) if a == b)
    return identiques / len(gauche) >= PART_IDENTIQUE


def retirer_repetition(precedent: str, nouveau: str) -> str:
    """Retire, en tête du nouveau texte, la fin déjà affichée par le précédent.

    Les tranches se chevauchent dans le temps (`application.veiller.RECOUVREMENT`),
    donc whisper retranscrit deux fois un passage à cheval : tronqué en fin de
    tranche, entier dans la suivante. `retenir` garde à raison cette seconde
    version — majoritairement neuve en temps — mais elle porte encore, en tête,
    les derniers mots déjà affichés : « dernier. » puis « dernier. Sandy, tu
    peux nous dire… ».

    La comparaison tolère la variante : le même passage n'est pas transcrit
    deux fois pareil, et exiger l'égalité mot pour mot laissait passer le
    doublon dès qu'un mot changeait.
    """
    avant = _mots_porteurs(precedent)
    apres = _mots_porteurs(nouveau)
    if not avant or not apres:
        return nouveau
    suffixe = [mot for mot, _ in avant]
    prefixe = [mot for mot, _ in apres]
    for longueur in range(min(len(suffixe), len(prefixe)), 0, -1):
        if not _se_recouvrent(suffixe[-longueur:], prefixe[:longueur]):
            continue
        if len(" ".join(prefixe[:longueur])) >= CARACTERES_RECOUVREMENT_MINIMUM:
            return nouveau[apres[longueur - 1][1]:].lstrip(" ,.;:!?-–—")
    return nouveau


#: En dessous, l'écart avec la personne suivante est trop mince pour qu'un nom
#: se lise comme le bon : c'est la même valeur que la marge exigée par la
#: reconnaissance, reprise ici pour que l'explication et la décision coïncident.
MARGE_LISIBLE = 0.06


class Certitude(StrEnum):
    """D'où vient le nom affiché. Détermine ce qu'on ose en faire.

    L'ordre compte : une source ne peut jamais être écrasée par une moins sûre.
    Sans cette règle, l'empreinte de la tranche suivante défaisait la correction
    qu'on venait de saisir.
    """

    HUMAINE = "humaine"        # quelqu'un l'a corrigé à la main
    CANAL = "canal"            # le micro le dit : c'est toi
    RECONNUE = "reconnue"      # la banque de voix reconnaît, marge suffisante
    PROBABLE = "probable"      # au-dessus du seuil, mais peu de matière
    INCONNUE = "inconnue"      # aucune idée, et on le dit

    @property
    def ferme(self) -> bool:
        """Vrai quand le nom n'est plus une hypothèse."""
        return self in {Certitude.HUMAINE, Certitude.CANAL}


#: Les sources, de la plus forte à la plus faible.
_FORCE = {
    Certitude.HUMAINE: 4,
    Certitude.CANAL: 3,
    Certitude.RECONNUE: 2,
    Certitude.PROBABLE: 1,
    Certitude.INCONNUE: 0,
}


@dataclass(frozen=True, slots=True)
class Bloc:
    """Des répliques consécutives venues de la même source.

    On attribue par bloc et non par réplique : whisper coupe à la phrase, et une
    empreinte tirée de six mots ne vaut rien. Regrouper ce qui se suit donne
    assez de matière pour reconnaître une voix, sans attendre la fin du tour.
    """

    repliques: tuple[Replique, ...]
    locale: bool

    @property
    def intervalle(self) -> Intervalle:
        return Intervalle(
            self.repliques[0].intervalle.debut, self.repliques[-1].intervalle.fin
        )


@dataclass(slots=True)
class VoixDirecte:
    """Une voix telle que le fil la connaît à cet instant."""

    identifiant: str
    nom: str | None = None
    certitude: Certitude = Certitude.INCONNUE
    rang: int = 0
    empreintes: list[Empreinte] = field(default_factory=list)
    #: Ce que la banque a répondu : ressemblance au nom retenu, et écart avec la
    #: personne suivante. Gardés parce que « Sophie ? » ne dit pas s'il s'agit
    #: d'une hypothèse fragile ou d'une quasi-certitude, et que c'est
    #: exactement ce qu'il faut savoir pour décider de corriger ou non.
    ressemblance: float = 0.0
    ecart: float = 0.0

    #: L'agrégat, gardé jusqu'à ce qu'une empreinte s'ajoute.
    #:
    #: Le rattachement compare la phrase courante à l'agrégat de **chaque**
    #: voix, et le recalculait à chaque comparaison : un agrégat pèse quelques
    #: centaines de nombres par empreinte, et le coût croît avec la réunion.
    #: Mesuré : treize millisecondes par phrase à mi-parcours, contre deux
    #: dixièmes de milliseconde au début.
    _agregat: Empreinte | None = field(default=None, repr=False)

    def ajouter(self, empreinte: Empreinte) -> None:
        """Verse une empreinte, et périme l'agrégat.

        Passer par ici plutôt que d'ajouter à la liste : c'est le seul endroit
        qui sache que l'agrégat doit être refait, et un `append` oublié ailleurs
        rendrait une voix reconnaissable à ce qu'elle était.
        """
        self.empreintes.append(empreinte)
        self._agregat = None

    def absorber(self, autre: VoixDirecte) -> None:
        """Reprend les empreintes d'une autre voix."""
        self.empreintes.extend(autre.empreintes)
        self._agregat = None

    def oublier_l_agregat(self) -> None:
        """Périme l'agrégat, quand la liste change sans passer par `ajouter`."""
        self._agregat = None

    @property
    def agregat(self) -> Empreinte:
        """L'empreinte moyenne de cette voix, calculée une fois par ajout."""
        if self._agregat is None:
            self._agregat = agreger(self.empreintes)
        return self._agregat

    @property
    def secondes(self) -> float:
        """Matière accumulée, pour savoir si l'empreinte vaut d'être gardée."""
        return sum(e.duree_source for e in self.empreintes)

    @property
    def etiquette(self) -> str:
        """Ce qui s'affiche à côté de la phrase.

        Le point d'interrogation n'est pas décoratif : il dit que le nom vient
        d'une empreinte et attend confirmation. Une réunion où tout s'affiche
        sans nuance est une réunion où personne ne corrige rien.
        """
        if self.nom is None:
            return NOM_INDETERMINE if self.identifiant == VOIX_INDETERMINEE else (
                f"Voix {self.rang}"
            )
        return self.nom if self.certitude.ferme else f"{self.nom} ?"

    @property
    def confiance(self) -> str:
        """Ce que la reconnaissance vaut, en clair. Vide quand elle n'a pas joué.

        Un chiffre nu ne se lit pas : 0,46 et 0,89 sont deux situations qui
        appellent des gestes différents, et personne ne connaît par cœur le
        seuil ni la marge. On dit donc ce qu'on en fait, et on donne le chiffre
        entre parenthèses pour qui veut vérifier.
        """
        if self.nom is None or not self.ressemblance:
            return ""
        if self.certitude is Certitude.HUMAINE:
            return "nommée à la main"
        if self.certitude is Certitude.CANAL:
            return "c'est ton micro"
        chiffres = f"ressemblance {self.ressemblance:.2f}, écart {self.ecart:.2f}"
        if self.certitude is Certitude.RECONNUE:
            return f"reconnue nettement ({chiffres})"
        # Sous le seuil, ou trop proche de quelqu'un d'autre : les deux cas se
        # distinguent, et le second est le plus trompeur — le nom est peut-être
        # celui du voisin.
        if self.ecart < MARGE_LISIBLE:
            return f"proche d'une autre voix, à confirmer ({chiffres})"
        return f"probable, peu de matière ({chiffres})"

    @property
    def nommable(self) -> bool:
        """Faux pour le fourre-tout des bribes : il mélange des personnes.

        Y appliquer un nom d'un coup attribuerait à quelqu'un les « oui » de
        tout le monde.
        """
        return self.identifiant != VOIX_INDETERMINEE


@dataclass(slots=True)
class TourDirect:
    """Une phrase affichée, et à qui le fil l'attribue."""

    numero: int
    intervalle: Intervalle
    texte: str
    voix: str


@dataclass(frozen=True, slots=True)
class Correction:
    """Ce qu'une correction humaine a changé, pour que l'appelant en tire les
    conséquences : réafficher, et verser l'empreinte à la banque de voix."""

    nom: str
    voix: str
    numeros: tuple[int, ...]
    #: Empreinte agrégée de la voix, quand elle porte assez de matière pour
    #: entrer en banque. `None` sinon : mieux vaut ne rien apprendre qu'apprendre
    #: une signature tirée de trois secondes de « d'accord ».
    empreinte: Empreinte | None = None
    #: La portée décidée, et non déduite du nombre de tours touchés : une voix
    #: qui n'a qu'un tour au moment du clic en aura d'autres ensuite, et la
    #: correction doit les couvrir.
    toute_la_voix: bool = True


def blocs(repliques: list[Replique], locaux: list[Intervalle]) -> list[Bloc]:
    """Regroupe les répliques en passages d'une même source.

    `locaux` vient de `canaux.tours_locaux` : les moments où le micro domine, et
    donc où c'est la personne qui enregistre qui parle. Une réplique est locale
    quand un de ces moments couvre la moitié de sa durée — le même critère que
    `canaux.retirer`, pour que les deux chemins ne se contredisent pas.
    """
    groupes: list[Bloc] = []
    courant: list[Replique] = []
    courant_local = False
    for replique in sorted(repliques, key=lambda r: r.intervalle.debut):
        locale = _est_locale(replique.intervalle, locaux)
        if courant and locale != courant_local:
            groupes.append(Bloc(tuple(courant), courant_local))
            courant = []
        courant.append(replique)
        courant_local = locale
    if courant:
        groupes.append(Bloc(tuple(courant), courant_local))
    return groupes


def _est_locale(intervalle: Intervalle, locaux: list[Intervalle]) -> bool:
    if intervalle.duree <= 0:
        return any(local.recouvrement(intervalle) > 0 for local in locaux)
    couvert = sum(local.recouvrement(intervalle) for local in locaux)
    return couvert / intervalle.duree >= 0.5



@dataclass(frozen=True, slots=True)
class Fusion:
    """Ce qu'il faut avoir gardé pour défaire une réunion de deux voix.

    Réunir deux voix mélange leurs empreintes dans un même tas et supprime la
    voix absorbée : sans cette trace, l'erreur est définitive. Elle l'a été
    pendant une réunion entière, où deux personnes réunies à tort sont restées
    une seule jusqu'au compte rendu.
    """

    source: str
    cible: str
    #: Les empreintes qui appartenaient à la source, pour les lui rendre.
    empreintes: tuple[Empreinte, ...]
    #: Les seuls tours qui ont changé d'étiquette lors de cette réunion.
    numeros: tuple[int, ...]
    nom: str | None
    certitude: Certitude
    rang: int
    ressemblance: float = 0.0
    ecart: float = 0.0
    #: L'état de la cible avant, qu'une correction humaine a pu changer après.
    nom_cible: str | None = None
    certitude_cible: Certitude = Certitude.INCONNUE

@dataclass
class Fil:
    """Le fil de la réunion en cours : ce qui a été dit, et par qui.

    Un seul objet, tenu par le processus qui écoute. La fenêtre n'en voit que le
    journal qu'il publie, et lui renvoie les corrections : deux processus, parce
    que faire tourner la transcription dans le fil de l'interface la gèle, et
    qu'un modèle qui tombe ne doit pas emporter la fenêtre.
    """

    #: Les personnes déjà en banque, pour reconnaître sans rien demander.
    connues: list[Personne] = field(default_factory=list)
    #: Le seuil du rattachement d'une phrase à une voix. Celui du direct, pas
    #: celui du recollage d'après réunion : on compare une phrase à un agrégat,
    #: et non deux agrégats.
    seuil_fusion: float = SEUIL_RATTACHEMENT_DIRECT
    #: Combien de personnes participent, si on le sait. Renseigné, le fil
    #: n'invente jamais plus de voix que de participants : une empreinte qui ne
    #: franchit pas le seuil rejoint la plus ressemblante. Laissé vide, chaque
    #: prise de parole qui n'atteint pas 0,75 crée une voix — inévitable sans
    #: cette information, et c'est la seule que la machine ne peut pas déduire.
    personnes: int | None = None
    #: La langue de la réunion. Neutre par défaut, jamais française : c'est
    #: l'appelant qui sait dans quelle langue on parle.
    profil: ProfilLinguistique = NEUTRE
    tours: list[TourDirect] = field(default_factory=list)
    voix: dict[str, VoixDirecte] = field(default_factory=dict)
    #: Fin du dernier tour inscrit : ce qui commence avant a déjà été affiché.
    jusqu_a: float = 0.0
    #: Compteur d'identifiants, jamais réutilisé. Une correction peut réunir deux
    #: voix, donc en faire disparaître une : recompter les voix présentes
    #: redonnerait un identifiant déjà porté par une autre.
    suite: int = 0
    #: Texte du dernier tour inscrit, pour retirer le recouvrement au tour
    #: suivant — celui-là seul peut être la suite immédiate de ce qui s'affiche.
    dernier_texte: str = ""
    #: Les réunions de voix déjà faites, dans l'ordre, pour pouvoir les défaire.
    fusions: list[Fusion] = field(default_factory=list)
    #: Les paires qu'un humain a séparées. Ni la mesure ni l'homonymie ne les
    #: réunissent de nouveau : sans cela, `recoller` refaisait la fusion à la
    #: tranche suivante et le clic n'avait servi à rien.
    separees: set[frozenset[str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.voix.setdefault(
            VOIX_LOCALE,
            VoixDirecte(VOIX_LOCALE, nom=NOM_LOCAL, certitude=Certitude.CANAL),
        )
        self.voix.setdefault(VOIX_INDETERMINEE, VoixDirecte(VOIX_INDETERMINEE))

    # ------------------------------------------------------------- lecture

    def etiquette(self, voix: str) -> str:
        connue = self.voix.get(voix)
        return connue.etiquette if connue else f"Voix {voix}"

    def rendu(self, depuis: float = 0.0) -> str:
        """Le fil en texte suivi, attribué, pour qu'on puisse l'interroger.

        La conversation exigeait un compte rendu, donc une réunion **terminée** :
        impossible de demander « qu'a-t-on décidé sur Oasis ? » pendant qu'on en
        parle, alors que le fil, lui, est déjà là. Les tours consécutifs d'une
        même voix sont regroupés, comme dans la transcription définitive : une
        étiquette par phrase rend le texte illisible pour qui doit le résumer.

        `depuis` coupe les premières secondes, pour n'interroger que la fin
        d'une longue réunion sans tout renvoyer.
        """
        lignes: list[str] = []
        courant: str | None = None
        for tour in self.tours:
            if tour.intervalle.fin < depuis or not tour.texte.strip():
                continue
            qui = self.etiquette(tour.voix)
            if qui != courant:
                lignes.append(f"\n[{qui}]")
                courant = qui
            minutes, secondes = divmod(int(tour.intervalle.debut), 60)
            lignes.append(f"{minutes:02d}:{secondes:02d}  {tour.texte.strip()}")
        return "\n".join(lignes).strip()

    def noms_proposables(self) -> list[str]:
        """Les noms qu'un menu de correction peut offrir sans rien inventer.

        Ceux de la réunion en cours d'abord — ce sont les plus probables — puis
        la banque, dont les habitués reviennent d'une réunion à l'autre.
        """
        vus = [v.nom for v in self.voix.values() if v.nom and v.nom != NOM_LOCAL]
        for personne in self.connues:
            if personne.nom not in vus:
                vus.append(personne.nom)
        return [NOM_LOCAL, *vus]

    def retenir(self, repliques: list[Replique]) -> list[Replique]:
        """Écarte ce qui a déjà été affiché lors de la tranche précédente.

        Le critère est la matière neuve, non le point de départ : une phrase que
        la tranche suivante fait commencer un peu plus tôt reste une phrase
        nouvelle, et la jeter en perdait une sur six à l'essai.
        """
        gardees: list[Replique] = []
        for replique in repliques:
            if not replique.texte.strip():
                continue
            # Un générique inventé par le modèle n'a été prononcé par personne :
            # affiché, il occupe une ligne du fil et se retrouve dans le compte
            # rendu comme une prise de parole.
            if est_un_generique(replique.texte, self.profil) or est_une_annotation(
                replique.texte
            ):
                continue
            duree = replique.intervalle.duree
            neuf = replique.intervalle.fin - max(replique.intervalle.debut, self.jusqu_a)
            if duree <= 0:
                if replique.intervalle.debut >= self.jusqu_a:
                    gardees.append(replique)
                continue
            if neuf / duree >= PART_NEUVE_MINIMALE:
                gardees.append(replique)
        if gardees:
            # Seule la première réplique retenue peut être la suite immédiate
            # du dernier tour affiché : les suivantes viennent d'un peu plus
            # tard dans la même tranche, sans recouvrement avec lui.
            gardees[0].texte = retirer_repetition(self.dernier_texte, gardees[0].texte)
        return gardees

    # ------------------------------------------------------------ écriture

    def rattacher(self, empreinte: Empreinte | None, locale: bool) -> str:
        """La voix à qui attribuer un bloc, en la créant s'il faut.

        L'ordre des tentatives est celui de la fiabilité : le canal, puis les
        voix déjà entendues dans cette réunion — enregistrées dans les mêmes
        conditions, donc comparables avec exigence — puis la banque, dont les
        empreintes viennent d'un autre jour et d'un autre matériel.
        """
        if locale:
            return VOIX_LOCALE
        if empreinte is None:
            return VOIX_INDETERMINEE

        proche = self._voix_la_plus_proche(empreinte)
        if proche is None and empreinte.duree_source < MATIERE_MINIMALE_VOIX:
            # Trop peu de matière pour fonder une personne. Mesuré sur une
            # réunion réelle : les voix qui portaient la réunion sont nées sur
            # 3 à 7 s de parole, celles qui n'existaient pas sur 1 à 1,5 s —
            # « lui. », « C'est ça. », « Trop bien. ». Une bribe rejoint la voix
            # la plus ressemblante ; s'il n'y en a aucune, elle attend qu'une
            # vraie voix existe.
            proche = self._la_moins_eloignee(empreinte) or VOIX_INDETERMINEE
        if proche is None:
            # Une voix déjà fournie l'emporte sur une voix de plus : c'est
            # l'adoption du recollage final, appliquée pendant la réunion.
            proche = self._voix_etablie_proche(empreinte)
        if proche is None and len(self._nommables()) >= VOIX_AU_PLUS:
            # Le plafond est atteint : une phrase de plus est de quelqu'un qui
            # est déjà là. Rejoindre la plus ressemblante vaut mieux que
            # d'inventer un treizième participant, et le fourre-tout attend
            # celles qui ne ressemblent à personne.
            proche = self._la_moins_eloignee(empreinte)
        if proche is None and self._au_complet():
            # Le nombre de participants est annoncé et toutes les voix
            # existent : une empreinte qui ne franchit pas le seuil rejoint
            # quand même la plus ressemblante, au lieu d'inventer une personne
            # de plus. Mesuré en présentiel : phrase à phrase, deux prises de
            # parole de la même personne se ressemblent à 0,69 en médiane, sous
            # le seuil de 0,75 — d'où une voix par tour de parole, vingt et une
            # pour trois personnes. Le nombre de participants est la seule
            # chose que la machine ne peut pas déduire ; quand on le lui donne,
            # elle n'a plus à deviner.
            proche = self._la_moins_eloignee(empreinte)
        if proche is not None:
            connue = self.voix[proche]
            connue.ajouter(empreinte)
            self._retenter_le_nom(connue)
            return proche

        nouvelle = VoixDirecte(
            identifiant=self._identifiant(), rang=self._rang(), empreintes=[empreinte]
        )
        self.voix[nouvelle.identifiant] = nouvelle
        self._retenter_le_nom(nouvelle)
        return nouvelle.identifiant

    def _nommables(self) -> list[VoixDirecte]:
        """Les voix qui désignent une personne : ni « Toi », ni le fourre-tout."""
        return [
            voix for identifiant, voix in self.voix.items()
            if identifiant not in (VOIX_LOCALE, VOIX_INDETERMINEE) and voix.empreintes
        ]

    def _au_complet(self) -> bool:
        """Vrai quand autant de voix existent que de participants annoncés."""
        if not self.personnes:
            return False
        # La personne qui enregistre compte parmi les participants, et son canal
        # la désigne déjà : elle n'occupe pas une des voix à répartir. Sa
        # présence se lit sur ses **tours**, pas sur ses empreintes : rien n'est
        # jamais prélevé sur la voix locale, le micro l'ayant déjà identifiée.
        a_parle = any(tour.voix == VOIX_LOCALE for tour in self.tours)
        distantes = self.personnes - (1 if a_parle else 0)
        return len(self._nommables()) >= max(1, distantes)

    def _la_moins_eloignee(self, empreinte: Empreinte) -> str | None:
        """La voix la plus ressemblante, seuil ou pas. Rien s'il n'y en a aucune."""
        classement = sorted(
            ((similarite(empreinte, v.agregat), v.identifiant)
             for v in self._nommables()),
            key=lambda x: (-x[0], x[1]),
        )
        return classement[0][1] if classement else None

    def _voix_etablie_proche(self, empreinte: Empreinte) -> str | None:
        """Une voix **déjà fournie** que cette empreinte rejoint sans hésitation.

        C'est la question de l'adoption du recollage final, posée pendant la
        réunion : « laquelle des voix établies ressemble le plus, et nettement
        plus ». Elle vaut ici pour la même raison qu'après coup — comparer une
        phrase à une voix qui porte une minute de parole est mieux posé que la
        comparer à une autre phrase.

        Ce qu'elle répare : sans nombre de participants annoncé, chaque prise de
        parole fondait une voix, parce que deux phrases d'une même personne ne
        se ressemblent qu'à 0,69 en médiane, sous le seuil de 0,75. Mesuré sur
        une réunion réelle de trois personnes, **cent onze voix** dans le fil.

        Le risque est borné par construction : seules les voix déjà fournies
        peuvent adopter, il faut une marge nette avec la suivante, et un clic
        défait l'attribution.
        """
        etablies = [
            (similarite(empreinte, v.agregat), v.identifiant)
            for v in self._nommables()
            if sum(e.duree_source for e in v.empreintes) >= MATIERE_ETABLIE
        ]
        if not etablies:
            return None
        classement = sorted(etablies, key=lambda x: (-x[0], x[1]))
        meilleur, laquelle = classement[0]
        second = classement[1][0] if len(classement) > 1 else -1.0
        if meilleur < SEUIL_ADOPTION or meilleur - second < MARGE_ADOPTION_DIRECT:
            return None
        return laquelle

    def _voix_la_plus_proche(self, empreinte: Empreinte) -> str | None:
        """La voix de cette réunion qui ressemble le plus, au-dessus du seuil.

        Le seuil de fusion, plus exigeant que celui de reconnaissance : au sein
        d'une même réunion les conditions d'enregistrement sont identiques, et
        confondre deux participants coûte plus cher que d'en afficher un de trop
        — celui-là, un clic le recolle.
        """
        classement = sorted(
            (
                (similarite(empreinte, v.agregat), v.identifiant)
                for v in self.voix.values()
                if v.empreintes
            ),
            key=lambda x: (-x[0], x[1]),
        )
        if not classement or classement[0][0] < self.seuil_fusion:
            return None
        # La marge, et non le seuil seul : les deux distributions se chevauchent
        # au décile, et c'est l'écart avec la deuxième voix qui rend ce
        # chevauchement sans conséquence. Deux voix qui se disputent la phrase à
        # égalité méritent le fourre-tout plutôt qu'un choix arbitraire.
        second = classement[1][0] if len(classement) > 1 else -1.0
        if classement[0][0] - second < MARGE_ADOPTION_DIRECT:
            return None
        return classement[0][1]

    def _retenter_le_nom(self, voix: VoixDirecte) -> None:
        """Redemande son nom à la banque, maintenant qu'il y a plus de matière.

        Une voix reste souvent anonyme à sa première bribe et devient
        reconnaissable trois phrases plus tard. Une correction humaine, elle,
        n'est jamais rejouée : c'est la seule source que rien ne discute.
        """
        if voix.certitude.ferme or not voix.empreintes:
            return
        if voix.secondes < MATIERE_POUR_RECONNAITRE:
            # Trop peu de matière pour croire un nom. On ne dit rien plutôt
            # que d'afficher une étiquette fausse, que l'oeil croira.
            return
        correspondance = reconnaitre(voix.agregat, self.connues)
        if correspondance is None:
            return
        trouvee = (
            Certitude.RECONNUE if correspondance.sure else Certitude.PROBABLE
        )
        if _FORCE[trouvee] < _FORCE[voix.certitude]:
            return
        voix.nom = correspondance.nom
        voix.certitude = trouvee
        voix.ressemblance = correspondance.similarite
        voix.ecart = correspondance.marge

    def inscrire(self, bloc: Bloc, voix: str) -> list[TourDirect]:
        """Ajoute les phrases d'un bloc au fil, attribuées à une voix."""
        nouveaux: list[TourDirect] = []
        for replique in bloc.repliques:
            tour = TourDirect(
                numero=len(self.tours) + 1,
                intervalle=replique.intervalle,
                texte=replique.texte.strip(),
                voix=voix,
            )
            self.tours.append(tour)
            nouveaux.append(tour)
            self.jusqu_a = max(self.jusqu_a, replique.intervalle.fin)
            if tour.texte:
                self.dernier_texte = tour.texte
        return nouveaux

    def corriger(self, numero: int, nom: str, toute_la_voix: bool = True) -> Correction:
        """Impose un nom, contre ce que l'empreinte croyait.

        Par défaut la correction porte sur **toute la voix** : quand l'outil se
        trompe de personne, il se trompe pour tous les passages de cette voix,
        et les reprendre un par un serait absurde. « Seulement cette phrase »
        existe pour le cas inverse — deux personnes qui se coupent, un passage
        tombé dans le mauvais groupe.

        La voix fourre-tout ne se nomme jamais en entier : elle mélange les
        bribes de tout le monde, et lui donner un nom d'un coup attribuerait à
        quelqu'un les « oui » des autres.
        """
        nom = nom.strip()
        if not nom:
            raise ValueError("un nom vide ne corrige rien")
        tour = self._tour(numero)
        ancienne = self.voix[tour.voix]
        if toute_la_voix and ancienne.nommable:
            return self._corriger_la_voix(ancienne, nom)
        return self._corriger_la_phrase(tour, nom)

    def _corriger_la_voix(self, voix: VoixDirecte, nom: str) -> Correction:
        fusion = self._voix_portant(nom)
        if fusion is not None and fusion.identifiant != voix.identifiant:
            # Le nom est déjà porté par une autre voix : l'outil avait découpé
            # une personne en deux. La correction les réunit.
            #
            # Y compris deux voix séparées à la main plus tôt : c'est un geste
            # humain qui revient sur un geste humain, et le dernier tranche.
            self.separees.discard(
                frozenset({voix.identifiant, fusion.identifiant})
            )
            self._absorber(voix.identifiant, fusion.identifiant)
            voix = fusion
        voix.nom = nom
        voix.certitude = Certitude.HUMAINE
        numeros = tuple(t.numero for t in self.tours if t.voix == voix.identifiant)
        return Correction(
            nom=nom, voix=voix.identifiant, numeros=numeros,
            empreinte=self.empreinte_a_apprendre(voix), toute_la_voix=True,
        )

    def _absorber(self, source: str, cible: str) -> None:
        """Verse une voix dans une autre : ses tours, puis ses empreintes.

        Consigne au passage de quoi défaire : les empreintes de la source et les
        seuls tours qui changent d'étiquette. Sans cette trace, une réunion
        fautive ne se répare pas — c'est arrivé en séance, sur deux personnes.
        """
        avalee = self.voix[source]
        gardee = self.voix[cible]
        deplaces = tuple(t.numero for t in self.tours if t.voix == source)
        self.fusions.append(Fusion(
            source=source, cible=cible,
            empreintes=tuple(avalee.empreintes), numeros=deplaces,
            nom=avalee.nom, certitude=avalee.certitude, rang=avalee.rang,
            ressemblance=avalee.ressemblance, ecart=avalee.ecart,
            nom_cible=gardee.nom, certitude_cible=gardee.certitude,
        ))
        gardee.absorber(avalee)
        for tour in self.tours:
            if tour.voix == source:
                tour.voix = cible
        del self.voix[source]

    def reunir(self, source: str, cible: str) -> Fusion | None:
        """Réunit deux voix en gardant de quoi défaire.

        Publique parce que la fenêtre rejoue les réunions depuis le journal :
        sans passer par ici, elles ne laissaient aucune trace de leur côté, et
        une réunion automatique — le cas le plus fréquent — restait indéfaisable
        depuis l'écran où on la voit.
        """
        if source == cible or source not in self.voix or cible not in self.voix:
            return None
        self._absorber(source, cible)
        return self.fusions[-1]

    def peut_separer(self, cible: str) -> bool:
        """Vrai quand cette voix a absorbé une autre qu'on peut lui reprendre."""
        return any(
            f.cible == cible and f.source not in self.voix for f in self.fusions
        )

    def separer(self, cible: str) -> Fusion | None:
        """Défait la dernière réunion qui a produit cette voix.

        Le geste que la réunion réclamait : dire « ces deux-là ne sont pas la
        même personne » après avoir dit le contraire, ou après que l'outil l'ait
        dit tout seul. La voix absorbée reprend son identifiant, ses empreintes
        et ses tours, et la paire est inscrite parmi celles qu'on ne réunit plus.

        Rend la fusion défaite, ou rien s'il n'y en avait aucune à défaire.
        """
        fusion = next(
            (f for f in reversed(self.fusions) if f.cible == cible), None
        )
        if fusion is None or fusion.source in self.voix:
            return None
        gardee = self.voix.get(cible)
        if gardee is None:
            return None
        rendue = VoixDirecte(
            identifiant=fusion.source, nom=fusion.nom,
            certitude=fusion.certitude, rang=fusion.rang,
            empreintes=list(fusion.empreintes),
            ressemblance=fusion.ressemblance, ecart=fusion.ecart,
        )
        # Retirées par identité et non par valeur : deux extraits d'une même
        # voix peuvent porter le même vecteur, et un `remove` par égalité
        # emporterait celui de la cible.
        a_rendre = {id(e) for e in fusion.empreintes}
        gardee.empreintes = [e for e in gardee.empreintes if id(e) not in a_rendre]
        gardee.oublier_l_agregat()
        # La cible retrouve ce qu'elle portait avant, sauf si un humain l'a
        # nommée depuis : sa décision est postérieure, elle l'emporte.
        if gardee.certitude is not Certitude.HUMAINE:
            gardee.nom, gardee.certitude = fusion.nom_cible, fusion.certitude_cible
        for tour in self.tours:
            if tour.voix == cible and tour.numero in set(fusion.numeros):
                tour.voix = fusion.source
        self.voix[fusion.source] = rendue
        self.fusions.remove(fusion)
        self.separees.add(frozenset({fusion.source, cible}))
        return fusion

    def _tenues_a_part(self, une: str, autre: str) -> bool:
        """Vrai quand un humain a déjà dit que ces deux voix ne sont pas la même."""
        return frozenset({une, autre}) in self.separees

    def recoller(self) -> list[tuple[str, str]]:
        """Réunit les voix que la matière accumulée montre être la même personne.

        Le rattachement d'un bloc compare **une** empreinte, souvent courte, à
        l'agrégat d'une voix, et cette comparaison n'est jamais refaite. Mesuré
        sur une réunion en présentiel : phrase à phrase, deux prises de parole
        de la même personne se ressemblent à 0,69 en médiane, sous le seuil de
        0,75 — donc chaque reprise créait une voix. Sur les agrégats accumulés,
        la même paire monte à 0,79, et deux personnes différentes restent à
        0,63. Le seuil n'était pas en cause : il n'était pas rejoué.

        C'est `fusionner_voix` qui décide, et **non** `recoller`, dont les trois
        passes servent le traitement final. La tentation était forte — mêmes
        seuils, rien de neuf à calibrer — et la mesure l'a écartée : rejoué sur
        mille neuf cent dix phrases d'une réunion réelle, le recollage complet
        appliqué toutes les dix secondes fait tomber la justesse des
        attributions de **93 % à 79,6 %**, c'est-à-dire au niveau qu'on
        obtiendrait en donnant tout à la voix la plus bavarde. Il fusionne tout.

        La raison tient à ce qu'il compare. Après la réunion, l'adoption
        rapproche des agrégats de plusieurs minutes ; ici, des agrégats de deux
        ou trois phrases, où 0,45 de ressemblance ne veut plus rien dire. Ce qui
        limite le nombre de voix en direct, c'est le plafond (`VOIX_AU_PLUS`) et
        le seuil de rattachement mesuré, pas un recollage plus gourmand.

        Deux voix nommées par un humain sous des noms différents ne sont jamais
        réunies : une correction humaine ne se laisse pas défaire par une
        mesure.
        """
        faits: list[tuple[str, str]] = []
        faits += self._reunir_les_homonymes()
        candidates = {
            identifiant: voix.empreintes
            for identifiant, voix in self.voix.items()
            if voix.empreintes and identifiant not in (VOIX_LOCALE, VOIX_INDETERMINEE)
        }
        if len(candidates) < 2:
            return faits
        for source, cible in fusionner_voix(candidates).items():
            if source == cible or source not in self.voix or cible not in self.voix:
                continue
            if self._noms_humains_differents(source, cible):
                continue
            if self._tenues_a_part(source, cible):
                continue
            self._absorber(source, cible)
            faits.append((source, cible))
        return faits

    def _reunir_les_homonymes(self) -> list[tuple[str, str]]:
        """Deux voix que la banque nomme pareil sont la même personne.

        L'auto-correction qui manquait, et elle ne coûte rien : quand la banque
        répond « Tanguy » sur trois voix distinctes, elle a déjà dit que ces
        trois voix sont de Tanguy. Attendre que leurs empreintes se ressemblent
        assez pour être réunies, c'est refuser une information qu'on tient.

        Mesuré en séance sur une réunion de trente-deux minutes : « Tanguy »
        s'affichait sur trois voix à la fois, dont deux avec un point
        d'interrogation. Le compte rendu en aurait annoncé trois.

        Un nom posé **à la main** n'entre pas dans ce jeu : deux corrections
        humaines de même nom sont déjà réunies par `corriger`, et deux noms
        humains différents ne se laissent pas défaire par une mesure.
        """
        par_nom: dict[str, list[VoixDirecte]] = {}
        for voix in self.voix.values():
            if voix.nom and voix.nommable and voix.identifiant != VOIX_LOCALE:
                par_nom.setdefault(voix.nom.casefold(), []).append(voix)
        faits: list[tuple[str, str]] = []
        for portantes in par_nom.values():
            if len(portantes) < 2:
                continue
            # La plus fournie garde son identifiant : c'est celle dont l'extrait
            # est le plus représentatif, et celle que l'oeil a le plus vue.
            portantes.sort(key=lambda v: -v.secondes)
            gardee = portantes[0]
            for absorbee in portantes[1:]:
                if self._tenues_a_part(absorbee.identifiant, gardee.identifiant):
                    continue
                self._absorber(absorbee.identifiant, gardee.identifiant)
                faits.append((absorbee.identifiant, gardee.identifiant))
        return faits

    def _noms_humains_differents(self, un: str, autre: str) -> bool:
        premier, second = self.voix[un], self.voix[autre]
        return (
            premier.certitude is Certitude.HUMAINE
            and second.certitude is Certitude.HUMAINE
            and premier.nom != second.nom
        )

    def _corriger_la_phrase(self, tour: TourDirect, nom: str) -> Correction:
        """Déplace une seule phrase, sans toucher au reste de la voix.

        La phrase rejoint la voix qui porte déjà ce nom si elle existe, pour que
        les tours de la même personne restent d'un seul tenant. Aucune empreinte
        n'est versée à la banque : le passage vient d'un groupe dont on vient
        justement de dire qu'il était mal formé.
        """
        cible = self._voix_portant(nom)
        if cible is None:
            cible = VoixDirecte(
                identifiant=self._identifiant(), nom=nom,
                certitude=Certitude.HUMAINE, rang=self._rang(),
            )
            self.voix[cible.identifiant] = cible
        tour.voix = cible.identifiant
        return Correction(nom=nom, voix=cible.identifiant,
                          numeros=(tour.numero,), toute_la_voix=False)

    def empreinte_a_apprendre(self, voix: VoixDirecte) -> Empreinte | None:
        """L'empreinte à verser en banque pour cette voix, s'il y a de quoi.

        Rien pour la personne qui enregistre : son micro la nomme, et ranger sa
        voix parmi les participants ne servirait qu'à l'exposer. Rien non plus
        sous le seuil de matière : une signature apprise sur trois secondes de
        « d'accord » abîmerait la reconnaissance des réunions suivantes.
        """
        if voix.identifiant == VOIX_LOCALE or not voix.empreintes:
            return None
        if voix.secondes < DUREE_POUR_LA_BANQUE_S:
            return None
        return voix.agregat

    def retenir_l_identifiant(self, identifiant: str) -> None:
        """Avance le compteur au-delà d'un identifiant venu d'ailleurs.

        Le journal nomme les voix « v1 », « v2 »… Les rejouer sans avancer le
        compteur lui fait redistribuer « v1 », qui **écrase** alors la voix
        existante : deux personnes sous un même identifiant, sans rien qui le
        signale. Le cas se produit à chaque reprise de fil.
        """
        if len(identifiant) < 2 or identifiant[0] != "v":
            return
        chiffres = identifiant[1:]
        if chiffres.isdigit():
            self.suite = max(self.suite, int(chiffres))

    def _identifiant(self) -> str:
        self.suite += 1
        # La ceinture, en plus de `retenir_l_identifiant` : un identifiant déjà
        # pris ne doit jamais ressortir, quelle que soit la façon dont la voix
        # est entrée dans le fil.
        while f"v{self.suite}" in self.voix:
            self.suite += 1
        return f"v{self.suite}"

    def _rang(self) -> int:
        """Numéro d'affichage d'une voix sans nom : « Voix 1 », « Voix 2 »…

        La personne qui enregistre n'y figure pas : son micro la nomme déjà.
        """
        return sum(
            1 for v in self.voix.values()
            if v.nommable and v.identifiant != VOIX_LOCALE
        ) + 1

    def _voix_portant(self, nom: str) -> VoixDirecte | None:
        replie = nom.casefold()
        for voix in self.voix.values():
            if voix.nom is not None and voix.nom.casefold() == replie:
                return voix
        return None

    def _tour(self, numero: int) -> TourDirect:
        for tour in self.tours:
            if tour.numero == numero:
                return tour
        raise KeyError(f"aucune phrase numéro {numero} dans le fil")
