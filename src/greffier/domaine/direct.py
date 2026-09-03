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
    SEUIL_FUSION,
    agreger,
    fusionner_voix,
    reconnaitre,
    similarite,
)
from greffier.domaine.generiques import est_un_generique
from greffier.domaine.modeles import Empreinte, Intervalle, Personne, Replique

#: Matière minimale pour **fonder** une voix. En deçà, une bribe rejoint la voix
#: la plus ressemblante plutôt que d'inventer une personne. Mesuré sur une
#: réunion en présentiel : les voix qui portaient réellement la réunion sont
#: nées sur 3,0 à 7,3 s de parole, les voix parasites sur 1,0 et 1,5 s. Trente
#: des cent soixante phrases duraient moins d'une seconde et demie.
#:
#: Rien à voir avec le seuil de ressemblance : une bribe peut ressembler
#: fortement à la mauvaise personne, c'est sa brièveté qui la rend suspecte.
MATIERE_MINIMALE_VOIX = 2.0

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

_MOT_DIRECT = re.compile(r"\S+")


def retirer_repetition(precedent: str, nouveau: str) -> str:
    """Retire, en tête du nouveau texte, la fin déjà affichée par le précédent.

    Les tranches se chevauchent dans le temps (`application.veiller.RECOUVREMENT`),
    donc whisper retranscrit deux fois un passage à cheval : tronqué en fin de
    tranche, entier dans la suivante. `retenir` garde à raison cette seconde
    version — majoritairement neuve en temps — mais elle porte encore, en tête,
    les derniers mots déjà affichés : « dernier. » puis « dernier. Sandy, tu
    peux nous dire… ».

    Comparaison mot à mot, sans casse ; le plus long recouvrement entre la fin
    du texte précédent et le début du nouveau est retiré, à condition de porter
    au moins `CARACTERES_RECOUVREMENT_MINIMUM` caractères.
    """
    mots_precedent = list(_MOT_DIRECT.finditer(precedent))
    mots_nouveau = list(_MOT_DIRECT.finditer(nouveau))
    if not mots_precedent or not mots_nouveau:
        return nouveau
    suffixe = [m.group().casefold() for m in mots_precedent]
    prefixe = [m.group().casefold() for m in mots_nouveau]
    for longueur in range(min(len(suffixe), len(prefixe)), 0, -1):
        if suffixe[-longueur:] != prefixe[:longueur]:
            continue
        recouvrement = " ".join(prefixe[:longueur])
        if len(recouvrement) >= CARACTERES_RECOUVREMENT_MINIMUM:
            return nouveau[mots_nouveau[longueur - 1].end():].lstrip(" ,.;:!?")
    return nouveau


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

    @property
    def toute_la_voix(self) -> bool:
        return len(self.numeros) > 1


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
    seuil_fusion: float = SEUIL_FUSION
    #: Combien de personnes participent, si on le sait. Renseigné, le fil
    #: n'invente jamais plus de voix que de participants : une empreinte qui ne
    #: franchit pas le seuil rejoint la plus ressemblante. Laissé vide, chaque
    #: prise de parole qui n'atteint pas 0,75 crée une voix — inévitable sans
    #: cette information, et c'est la seule que la machine ne peut pas déduire.
    personnes: int | None = None
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
            if est_un_generique(replique.texte):
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
            connue.empreintes.append(empreinte)
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
            ((similarite(empreinte, agreger(v.empreintes)), v.identifiant)
             for v in self._nommables()),
            key=lambda x: (-x[0], x[1]),
        )
        return classement[0][1] if classement else None

    def _voix_la_plus_proche(self, empreinte: Empreinte) -> str | None:
        """La voix de cette réunion qui ressemble le plus, au-dessus du seuil.

        Le seuil de fusion, plus exigeant que celui de reconnaissance : au sein
        d'une même réunion les conditions d'enregistrement sont identiques, et
        confondre deux participants coûte plus cher que d'en afficher un de trop
        — celui-là, un clic le recolle.
        """
        classement = sorted(
            (
                (similarite(empreinte, agreger(v.empreintes)), v.identifiant)
                for v in self.voix.values()
                if v.empreintes
            ),
            key=lambda x: (-x[0], x[1]),
        )
        if not classement or classement[0][0] < self.seuil_fusion:
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
        correspondance = reconnaitre(agreger(voix.empreintes), self.connues)
        if correspondance is None:
            return
        trouvee = (
            Certitude.RECONNUE if correspondance.sure else Certitude.PROBABLE
        )
        if _FORCE[trouvee] < _FORCE[voix.certitude]:
            return
        voix.nom = correspondance.nom
        voix.certitude = trouvee

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
            self._absorber(voix.identifiant, fusion.identifiant)
            voix = fusion
        voix.nom = nom
        voix.certitude = Certitude.HUMAINE
        numeros = tuple(t.numero for t in self.tours if t.voix == voix.identifiant)
        return Correction(
            nom=nom, voix=voix.identifiant, numeros=numeros,
            empreinte=self.empreinte_a_apprendre(voix),
        )

    def _absorber(self, source: str, cible: str) -> None:
        """Verse une voix dans une autre : ses tours, puis ses empreintes."""
        avalee = self.voix[source]
        gardee = self.voix[cible]
        gardee.empreintes.extend(avalee.empreintes)
        for tour in self.tours:
            if tour.voix == source:
                tour.voix = cible
        del self.voix[source]

    def recoller(self) -> list[tuple[str, str]]:
        """Réunit les voix que la matière accumulée montre être la même personne.

        Le rattachement d'un bloc compare **une** empreinte, souvent courte, à
        l'agrégat d'une voix, et cette comparaison n'est jamais refaite. Mesuré
        sur une réunion en présentiel : phrase à phrase, deux prises de parole
        de la même personne se ressemblent à 0,69 en médiane, sous le seuil de
        0,75 — donc chaque reprise créait une voix. Sur les agrégats accumulés,
        la même paire monte à 0,79, et deux personnes différentes restent à
        0,63. Le seuil n'était pas en cause : il n'était pas rejoué.

        C'est `fusionner_voix`, celle du traitement final, qui décide : même
        seuil, même garde de matière minimale, rien de neuf à calibrer. Deux
        voix nommées par un humain sous des noms différents ne sont jamais
        réunies — une correction humaine ne se laisse pas défaire par une
        mesure.
        """
        candidates = {
            identifiant: voix.empreintes
            for identifiant, voix in self.voix.items()
            if voix.empreintes and identifiant not in (VOIX_LOCALE, VOIX_INDETERMINEE)
        }
        if len(candidates) < 2:
            return []
        faits: list[tuple[str, str]] = []
        for source, cible in fusionner_voix(candidates).items():
            if source == cible or source not in self.voix or cible not in self.voix:
                continue
            if self._noms_humains_differents(source, cible):
                continue
            self._absorber(source, cible)
            faits.append((source, cible))
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
        return Correction(nom=nom, voix=cible.identifiant, numeros=(tour.numero,))

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
        return agreger(voix.empreintes)

    def _identifiant(self) -> str:
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
