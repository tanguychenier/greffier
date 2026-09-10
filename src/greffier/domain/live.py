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

from greffier.domain.boilerplate import is_an_annotation, is_boilerplate
from greffier.domain.channels import VOIX_LOCALE
from greffier.domain.language import LanguageProfile
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.profiles.neutral import NEUTRAL
from greffier.domain.questions import distance
from greffier.domain.voiceprints import (
    MATIERE_ETABLIE,
    SEUIL_ADOPTION,
    aggregate,
    join_voices,
    recognise,
    similarity,
)

MATIERE_MINIMALE_VOIX = 2.0

MATIERE_POUR_RECONNAITRE = 6.0

MARGE_ADOPTION_DIRECT = 0.06

SEUIL_RATTACHEMENT_DIRECT = 0.50

VOIX_AU_PLUS = 12

NOM_LOCAL = "Toi"

VOIX_INDETERMINEE = "?"
NOM_INDETERMINE = "Les autres"

PART_NEUVE_MINIMALE = 0.5

DUREE_POUR_LA_BANQUE_S = 3.0

CARACTERES_RECOUVREMENT_MINIMUM = 4

MOTS_POUR_TOLERER = 3

PART_IDENTIQUE = 0.5

_MOT_DIRECT = re.compile(r"\S+")
_PONCTUATION_MOT = ".,;:!?…\"'«»()[]-–—"

def _content_words(text: str) -> list[tuple[str, int]]:
    """Les mots qui portent du sens, chacun avec sa fin dans le texte.

    La ponctuation seule est écartée : le modèle préfixe une réplique d'un
    tiret de dialogue, et comparer « - » à « Qu'est-ce » faisait échouer la
    comparaison au premier mot, donc ne coupait rien du tout.
    """
    trouves: list[tuple[str, int]] = []
    for mot in _MOT_DIRECT.finditer(text):
        nu = mot.group().strip(_PONCTUATION_MOT).casefold()
        if nu:
            trouves.append((nu, mot.end()))
    return trouves

def _same_word(un: str, autre: str) -> bool:
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

def _overlap_each_other(gauche: list[str], droite: list[str]) -> bool:
    """Vrai si ces deux suites de mots sont le même passage, dit deux fois."""
    if gauche == droite:
        return True
    if len(gauche) < MOTS_POUR_TOLERER:
        return False
    # Tous les mots doivent au moins être des variantes l'un de l'autre : sans
    # cela, « on va faire ça » et « on va faire autrement » se recouvriraient
    # sur trois mots et la phrase neuve disparaîtrait.
    if not all(_same_word(a, b) for a, b in zip(gauche, droite, strict=True)):
        return False
    identiques = sum(1 for a, b in zip(gauche, droite, strict=True) if a == b)
    return identiques / len(gauche) >= PART_IDENTIQUE

def drop_repetition(precedent: str, nouveau: str) -> str:
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
    avant = _content_words(precedent)
    apres = _content_words(nouveau)
    if not avant or not apres:
        return nouveau
    suffixe = [mot for mot, _ in avant]
    prefixe = [mot for mot, _ in apres]
    for length in range(min(len(suffixe), len(prefixe)), 0, -1):
        if not _overlap_each_other(suffixe[-length:], prefixe[:length]):
            continue
        if len(" ".join(prefixe[:length])) >= CARACTERES_RECOUVREMENT_MINIMUM:
            return nouveau[apres[length - 1][1]:].lstrip(" ,.;:!?-–—")
    return nouveau

MARGE_LISIBLE = 0.06

class Certainty(StrEnum):
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
    def firm(self) -> bool:
        """Vrai quand le nom n'est plus une hypothèse."""
        return self in {Certainty.HUMAINE, Certainty.CANAL}

_WEIGHT = {
    Certainty.HUMAINE: 4,
    Certainty.CANAL: 3,
    Certainty.RECONNUE: 2,
    Certainty.PROBABLE: 1,
    Certainty.INCONNUE: 0,
}

@dataclass(frozen=True, slots=True)
class Block:
    """Des répliques consécutives venues de la même source.

    On attribue par bloc et non par réplique : whisper coupe à la phrase, et une
    empreinte tirée de six mots ne vaut rien. Regrouper ce qui se suit donne
    assez de matière pour reconnaître une voix, sans attendre la fin du tour.
    """

    utterances: tuple[Utterance, ...]
    locale: bool

    @property
    def span(self) -> Span:
        return Span(
            self.utterances[0].span.start, self.utterances[-1].span.end
        )

@dataclass(slots=True)
class LiveVoice:
    """Une voix telle que le fil la connaît à cet instant."""

    identifier: str
    name: str | None = None
    certitude: Certainty = Certainty.INCONNUE
    rank: int = 0
    voiceprints: list[Voiceprint] = field(default_factory=list)
    likeness: float = 0.0
    gap: float = 0.0

    _aggregate_of: Voiceprint | None = field(default=None, repr=False)

    def add(self, voiceprint: Voiceprint) -> None:
        """Verse une empreinte, et périme l'agrégat.

        Passer par ici plutôt que d'ajouter à la liste : c'est le seul endroit
        qui sache que l'agrégat doit être refait, et un `append` oublié ailleurs
        rendrait une voix reconnaissable à ce qu'elle était.
        """
        self.voiceprints.append(voiceprint)
        self._aggregate_of = None

    def absorb(self, autre: LiveVoice) -> None:
        """Reprend les empreintes d'une autre voix."""
        self.voiceprints.extend(autre.voiceprints)
        self._aggregate_of = None

    def forget_aggregate(self) -> None:
        """Périme l'agrégat, quand la liste change sans passer par `ajouter`."""
        self._aggregate_of = None

    @property
    def aggregate_of(self) -> Voiceprint:
        """L'empreinte moyenne de cette voix, calculée une fois par ajout."""
        if self._aggregate_of is None:
            self._aggregate_of = aggregate(self.voiceprints)
        return self._aggregate_of

    @property
    def seconds(self) -> float:
        """Matière accumulée, pour savoir si l'empreinte vaut d'être gardée."""
        return sum(e.source_duration for e in self.voiceprints)

    @property
    def label(self) -> str:
        """Ce qui s'affiche à côté de la phrase.

        Le point d'interrogation n'est pas décoratif : il dit que le nom vient
        d'une empreinte et attend confirmation. Une réunion où tout s'affiche
        sans nuance est une réunion où personne ne corrige rien.
        """
        if self.name is None:
            return NOM_INDETERMINE if self.identifier == VOIX_INDETERMINEE else (
                f"Voix {self.rank}"
            )
        return self.name if self.certitude.firm else f"{self.name} ?"

    @property
    def confidence(self) -> str:
        """Ce que la reconnaissance vaut, en clair. Vide quand elle n'a pas joué.

        Un chiffre nu ne se lit pas : 0,46 et 0,89 sont deux situations qui
        appellent des gestes différents, et personne ne connaît par cœur le
        seuil ni la marge. On dit donc ce qu'on en fait, et on donne le chiffre
        entre parenthèses pour qui veut vérifier.
        """
        if self.name is None or not self.likeness:
            return ""
        if self.certitude is Certainty.HUMAINE:
            return "nommée à la main"
        if self.certitude is Certainty.CANAL:
            return "c'est ton micro"
        chiffres = f"ressemblance {self.likeness:.2f}, écart {self.gap:.2f}"
        if self.certitude is Certainty.RECONNUE:
            return f"reconnue nettement ({chiffres})"
        # Sous le seuil, ou trop proche de quelqu'un d'autre : les deux cas se
        # distinguent, et le second est le plus trompeur — le nom est peut-être
        # celui du voisin.
        if self.gap < MARGE_LISIBLE:
            return f"proche d'une autre voix, à confirmer ({chiffres})"
        return f"probable, peu de matière ({chiffres})"

    @property
    def nameable(self) -> bool:
        """Faux pour le fourre-tout des bribes : il mélange des personnes.

        Y appliquer un nom d'un coup attribuerait à quelqu'un les « oui » de
        tout le monde.
        """
        return self.identifier != VOIX_INDETERMINEE

@dataclass(slots=True)
class LiveTurn:
    """Une phrase affichée, et à qui le fil l'attribue."""

    number: int
    span: Span
    text: str
    voice: str

@dataclass(frozen=True, slots=True)
class Correction:
    """Ce qu'une correction humaine a changé, pour que l'appelant en tire les
    conséquences : réafficher, et verser l'empreinte à la banque de voix."""

    name: str
    voice: str
    numeros: tuple[int, ...]
    voiceprint: Voiceprint | None = None
    whole_voice: bool = True

def blocks(utterances: list[Utterance], locaux: list[Span]) -> list[Block]:
    """Regroupe les répliques en passages d'une même source.

    `locaux` vient de `canaux.tours_locaux` : les moments où le micro domine, et
    donc où c'est la personne qui enregistre qui parle. Une réplique est locale
    quand un de ces moments couvre la moitié de sa durée — le même critère que
    `canaux.retirer`, pour que les deux chemins ne se contredisent pas.
    """
    groupes: list[Block] = []
    current: list[Utterance] = []
    courant_local = False
    for utterance in sorted(utterances, key=lambda r: r.span.start):
        locale = _is_local(utterance.span, locaux)
        if current and locale != courant_local:
            groupes.append(Block(tuple(current), courant_local))
            current = []
        current.append(utterance)
        courant_local = locale
    if current:
        groupes.append(Block(tuple(current), courant_local))
    return groupes

def _is_local(span: Span, locaux: list[Span]) -> bool:
    if span.duration <= 0:
        return any(local.overlap(span) > 0 for local in locaux)
    couvert = sum(local.overlap(span) for local in locaux)
    return couvert / span.duration >= 0.5

@dataclass(frozen=True, slots=True)
class Join:
    """Ce qu'il faut avoir gardé pour défaire une réunion de deux voix.

    Réunir deux voix mélange leurs empreintes dans un même tas et supprime la
    voix absorbée : sans cette trace, l'erreur est définitive. Elle l'a été
    pendant une réunion entière, où deux personnes réunies à tort sont restées
    une seule jusqu'au compte rendu.
    """

    source: str
    target: str
    voiceprints: tuple[Voiceprint, ...]
    numeros: tuple[int, ...]
    name: str | None
    certitude: Certainty
    rank: int
    likeness: float = 0.0
    gap: float = 0.0
    nom_cible: str | None = None
    certitude_cible: Certainty = Certainty.INCONNUE

@dataclass
class LiveThread:
    """Le fil de la réunion en cours : ce qui a été dit, et par qui.

    Un seul objet, tenu par le processus qui écoute. La fenêtre n'en voit que le
    journal qu'il publie, et lui renvoie les corrections : deux processus, parce
    que faire tourner la transcription dans le fil de l'interface la gèle, et
    qu'un modèle qui tombe ne doit pas emporter la fenêtre.
    """

    connues: list[Person] = field(default_factory=list)
    seuil_fusion: float = SEUIL_RATTACHEMENT_DIRECT
    people: int | None = None
    profil: LanguageProfile = NEUTRAL
    turns: list[LiveTurn] = field(default_factory=list)
    voice: dict[str, LiveVoice] = field(default_factory=dict)
    jusqu_a: float = 0.0
    suite: int = 0
    dernier_texte: str = ""
    fusions: list[Join] = field(default_factory=list)
    split_apart: set[frozenset[str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.voice.setdefault(
            VOIX_LOCALE,
            LiveVoice(VOIX_LOCALE, name=NOM_LOCAL, certitude=Certainty.CANAL),
        )
        self.voice.setdefault(VOIX_INDETERMINEE, LiveVoice(VOIX_INDETERMINEE))

    # ------------------------------------------------------------- lecture

    def label(self, voice: str) -> str:
        connue = self.voice.get(voice)
        return connue.label if connue else f"Voix {voice}"

    def rendered(self, depuis: float = 0.0) -> str:
        """Le fil en texte suivi, attribué, pour qu'on puisse l'interroger.

        La conversation exigeait un compte rendu, donc une réunion **terminée** :
        impossible de demander « qu'a-t-on décidé sur Oasis ? » pendant qu'on en
        parle, alors que le fil, lui, est déjà là. Les tours consécutifs d'une
        même voix sont regroupés, comme dans la transcription définitive : une
        étiquette par phrase rend le texte illisible pour qui doit le résumer.

        `depuis` coupe les premières secondes, pour n'interroger que la fin
        d'une longue réunion sans tout renvoyer.
        """
        lines: list[str] = []
        current: str | None = None
        for turn in self.turns:
            if turn.span.end < depuis or not turn.text.strip():
                continue
            qui = self.label(turn.voice)
            if qui != current:
                lines.append(f"\n[{qui}]")
                current = qui
            minutes, seconds = divmod(int(turn.span.start), 60)
            lines.append(f"{minutes:02d}:{seconds:02d}  {turn.text.strip()}")
        return "\n".join(lines).strip()

    def suggestable_names(self) -> list[str]:
        """Les noms qu'un menu de correction peut offrir sans rien inventer.

        Ceux de la réunion en cours d'abord — ce sont les plus probables — puis
        la banque, dont les habitués reviennent d'une réunion à l'autre.
        """
        vus = [v.name for v in self.voice.values() if v.name and v.name != NOM_LOCAL]
        for personne in self.connues:
            if personne.name not in vus:
                vus.append(personne.name)
        return [NOM_LOCAL, *vus]

    def retenir(self, utterances: list[Utterance]) -> list[Utterance]:
        """Écarte ce qui a déjà été affiché lors de la tranche précédente.

        Le critère est la matière neuve, non le point de départ : une phrase que
        la tranche suivante fait commencer un peu plus tôt reste une phrase
        nouvelle, et la jeter en perdait une sur six à l'essai.
        """
        kept: list[Utterance] = []
        for utterance in utterances:
            if not utterance.text.strip():
                continue
            # Un générique inventé par le modèle n'a été prononcé par personne :
            # affiché, il occupe une ligne du fil et se retrouve dans le compte
            # rendu comme une prise de parole.
            if is_boilerplate(utterance.text, self.profil) or is_an_annotation(
                utterance.text
            ):
                continue
            duration = utterance.span.duration
            neuf = utterance.span.end - max(utterance.span.start, self.jusqu_a)
            if duration <= 0:
                if utterance.span.start >= self.jusqu_a:
                    kept.append(utterance)
                continue
            if neuf / duration >= PART_NEUVE_MINIMALE:
                kept.append(utterance)
        if kept:
            # Seule la première réplique retenue peut être la suite immédiate
            # du dernier tour affiché : les suivantes viennent d'un peu plus
            # tard dans la même tranche, sans recouvrement avec lui.
            kept[0].text = drop_repetition(self.dernier_texte, kept[0].text)
        return kept

    # ------------------------------------------------------------ écriture

    def attach(self, voiceprint: Voiceprint | None, locale: bool) -> str:
        """La voix à qui attribuer un bloc, en la créant s'il faut.

        L'ordre des tentatives est celui de la fiabilité : le canal, puis les
        voix déjà entendues dans cette réunion — enregistrées dans les mêmes
        conditions, donc comparables avec exigence — puis la banque, dont les
        empreintes viennent d'un autre jour et d'un autre matériel.
        """
        if locale:
            return VOIX_LOCALE
        if voiceprint is None:
            return VOIX_INDETERMINEE

        proche = self._closest_voice(voiceprint)
        if proche is None and voiceprint.source_duration < MATIERE_MINIMALE_VOIX:
            # Trop peu de matière pour fonder une personne. Mesuré sur une
            # réunion réelle : les voix qui portaient la réunion sont nées sur
            # 3 à 7 s de parole, celles qui n'existaient pas sur 1 à 1,5 s —
            # « lui. », « C'est ça. », « Trop bien. ». Une bribe rejoint la voix
            # la plus ressemblante ; s'il n'y en a aucune, elle attend qu'une
            # vraie voix existe.
            proche = self._the_least_distant(voiceprint) or VOIX_INDETERMINEE
        if proche is None:
            # Une voix déjà fournie l'emporte sur une voix de plus : c'est
            # l'adoption du recollage final, appliquée pendant la réunion.
            proche = self._nearby_established_voice(voiceprint)
        if proche is None and len(self._nameable_ones()) >= VOIX_AU_PLUS:
            # Le plafond est atteint : une phrase de plus est de quelqu'un qui
            # est déjà là. Rejoindre la plus ressemblante vaut mieux que
            # d'inventer un treizième participant, et le fourre-tout attend
            # celles qui ne ressemblent à personne.
            proche = self._the_least_distant(voiceprint)
        if proche is None and self._in_full():
            # Le nombre de participants est annoncé et toutes les voix
            # existent : une empreinte qui ne franchit pas le seuil rejoint
            # quand même la plus ressemblante, au lieu d'inventer une personne
            # de plus. Mesuré en présentiel : phrase à phrase, deux prises de
            # parole de la même personne se ressemblent à 0,69 en médiane, sous
            # le seuil de 0,75 — d'où une voix par tour de parole, vingt et une
            # pour trois personnes. Le nombre de participants est la seule
            # chose que la machine ne peut pas déduire ; quand on le lui donne,
            # elle n'a plus à deviner.
            proche = self._the_least_distant(voiceprint)
        if proche is not None:
            connue = self.voice[proche]
            connue.add(voiceprint)
            self._retenter_le_nom(connue)
            return proche

        nouvelle = LiveVoice(
            identifier=self._identifier(), rank=self._rank(), voiceprints=[voiceprint]
        )
        self.voice[nouvelle.identifier] = nouvelle
        self._retenter_le_nom(nouvelle)
        return nouvelle.identifier

    def _nameable_ones(self) -> list[LiveVoice]:
        """Les voix qui désignent une personne : ni « Toi », ni le fourre-tout."""
        return [
            voice for identifier, voice in self.voice.items()
            if identifier not in (VOIX_LOCALE, VOIX_INDETERMINEE) and voice.voiceprints
        ]

    def _in_full(self) -> bool:
        """Vrai quand autant de voix existent que de participants annoncés."""
        if not self.people:
            return False
        # La personne qui enregistre compte parmi les participants, et son canal
        # la désigne déjà : elle n'occupe pas une des voix à répartir. Sa
        # présence se lit sur ses **tours**, pas sur ses empreintes : rien n'est
        # jamais prélevé sur la voix locale, le micro l'ayant déjà identifiée.
        has_spoken = any(turn.voice == VOIX_LOCALE for turn in self.turns)
        distantes = self.people - (1 if has_spoken else 0)
        return len(self._nameable_ones()) >= max(1, distantes)

    def _the_least_distant(self, voiceprint: Voiceprint) -> str | None:
        """La voix la plus ressemblante, seuil ou pas. Rien s'il n'y en a aucune."""
        ranking = sorted(
            ((similarity(voiceprint, v.aggregate_of), v.identifier)
             for v in self._nameable_ones()),
            key=lambda x: (-x[0], x[1]),
        )
        return ranking[0][1] if ranking else None

    def _nearby_established_voice(self, voiceprint: Voiceprint) -> str | None:
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
            (similarity(voiceprint, v.aggregate_of), v.identifier)
            for v in self._nameable_ones()
            if sum(e.source_duration for e in v.voiceprints) >= MATIERE_ETABLIE
        ]
        if not etablies:
            return None
        ranking = sorted(etablies, key=lambda x: (-x[0], x[1]))
        best, laquelle = ranking[0]
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if best < SEUIL_ADOPTION or best - second < MARGE_ADOPTION_DIRECT:
            return None
        return laquelle

    def _closest_voice(self, voiceprint: Voiceprint) -> str | None:
        """La voix de cette réunion qui ressemble le plus, au-dessus du seuil.

        Le seuil de fusion, plus exigeant que celui de reconnaissance : au sein
        d'une même réunion les conditions d'enregistrement sont identiques, et
        confondre deux participants coûte plus cher que d'en afficher un de trop
        — celui-là, un clic le recolle.
        """
        ranking = sorted(
            (
                (similarity(voiceprint, v.aggregate_of), v.identifier)
                for v in self.voice.values()
                if v.voiceprints
            ),
            key=lambda x: (-x[0], x[1]),
        )
        if not ranking or ranking[0][0] < self.seuil_fusion:
            return None
        # La marge, et non le seuil seul : les deux distributions se chevauchent
        # au décile, et c'est l'écart avec la deuxième voix qui rend ce
        # chevauchement sans conséquence. Deux voix qui se disputent la phrase à
        # égalité méritent le fourre-tout plutôt qu'un choix arbitraire.
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if ranking[0][0] - second < MARGE_ADOPTION_DIRECT:
            return None
        return ranking[0][1]

    def _retenter_le_nom(self, voice: LiveVoice) -> None:
        """Redemande son nom à la banque, maintenant qu'il y a plus de matière.

        Une voix reste souvent anonyme à sa première bribe et devient
        reconnaissable trois phrases plus tard. Une correction humaine, elle,
        n'est jamais rejouée : c'est la seule source que rien ne discute.
        """
        if voice.certitude.firm or not voice.voiceprints:
            return
        if voice.seconds < MATIERE_POUR_RECONNAITRE:
            # Trop peu de matière pour croire un nom. On ne dit rien plutôt
            # que d'afficher une étiquette fausse, que l'oeil croira.
            return
        match = recognise(voice.aggregate_of, self.connues)
        if match is None:
            return
        trouvee = (
            Certainty.RECONNUE if match.sure else Certainty.PROBABLE
        )
        if _WEIGHT[trouvee] < _WEIGHT[voice.certitude]:
            return
        voice.name = match.name
        voice.certitude = trouvee
        voice.likeness = match.similarity
        voice.gap = match.marge

    def record_turn(self, bloc: Block, voice: str) -> list[LiveTurn]:
        """Ajoute les phrases d'un bloc au fil, attribuées à une voix."""
        nouveaux: list[LiveTurn] = []
        for utterance in bloc.utterances:
            turn = LiveTurn(
                number=len(self.turns) + 1,
                span=utterance.span,
                text=utterance.text.strip(),
                voice=voice,
            )
            self.turns.append(turn)
            nouveaux.append(turn)
            self.jusqu_a = max(self.jusqu_a, utterance.span.end)
            if turn.text:
                self.dernier_texte = turn.text
        return nouveaux

    def correct(self, number: int, name: str, whole_voice: bool = True) -> Correction:
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
        name = name.strip()
        if not name:
            raise ValueError("un nom vide ne corrige rien")
        turn = self._turn(number)
        ancienne = self.voice[turn.voice]
        if whole_voice and ancienne.nameable:
            return self._correct_the_voice(ancienne, name)
        return self._correct_the_sentence(turn, name)

    def _correct_the_voice(self, voice: LiveVoice, name: str) -> Correction:
        fusion = self._voice_named(name)
        if fusion is not None and fusion.identifier != voice.identifier:
            # Le nom est déjà porté par une autre voix : l'outil avait découpé
            # une personne en deux. La correction les réunit.
            #
            # Y compris deux voix séparées à la main plus tôt : c'est un geste
            # humain qui revient sur un geste humain, et le dernier tranche.
            self.split_apart.discard(
                frozenset({voice.identifier, fusion.identifier})
            )
            self._absorb(voice.identifier, fusion.identifier)
            voice = fusion
        voice.name = name
        voice.certitude = Certainty.HUMAINE
        numeros = tuple(t.number for t in self.turns if t.voice == voice.identifier)
        return Correction(
            name=name, voice=voice.identifier, numeros=numeros,
            voiceprint=self.voiceprint_to_learn(voice), whole_voice=True,
        )

    def _absorb(self, source: str, target: str) -> None:
        """Verse une voix dans une autre : ses tours, puis ses empreintes.

        Consigne au passage de quoi défaire : les empreintes de la source et les
        seuls tours qui changent d'étiquette. Sans cette trace, une réunion
        fautive ne se répare pas — c'est arrivé en séance, sur deux personnes.
        """
        avalee = self.voice[source]
        gardee = self.voice[target]
        deplaces = tuple(t.number for t in self.turns if t.voice == source)
        self.fusions.append(Join(
            source=source, target=target,
            voiceprints=tuple(avalee.voiceprints), numeros=deplaces,
            name=avalee.name, certitude=avalee.certitude, rank=avalee.rank,
            likeness=avalee.likeness, gap=avalee.gap,
            nom_cible=gardee.name, certitude_cible=gardee.certitude,
        ))
        gardee.absorb(avalee)
        for turn in self.turns:
            if turn.voice == source:
                turn.voice = target
        del self.voice[source]

    def join_into(self, source: str, target: str) -> Join | None:
        """Réunit deux voix en gardant de quoi défaire.

        Publique parce que la fenêtre rejoue les réunions depuis le journal :
        sans passer par ici, elles ne laissaient aucune trace de leur côté, et
        une réunion automatique — le cas le plus fréquent — restait indéfaisable
        depuis l'écran où on la voit.
        """
        if source == target or source not in self.voice or target not in self.voice:
            return None
        self._absorb(source, target)
        return self.fusions[-1]

    def can_split(self, target: str) -> bool:
        """Vrai quand cette voix a absorbé une autre qu'on peut lui reprendre."""
        return any(
            f.target == target and f.source not in self.voice for f in self.fusions
        )

    def split(self, target: str) -> Join | None:
        """Défait la dernière réunion qui a produit cette voix.

        Le geste que la réunion réclamait : dire « ces deux-là ne sont pas la
        même personne » après avoir dit le contraire, ou après que l'outil l'ait
        dit tout seul. La voix absorbée reprend son identifiant, ses empreintes
        et ses tours, et la paire est inscrite parmi celles qu'on ne réunit plus.

        Rend la fusion défaite, ou rien s'il n'y en avait aucune à défaire.
        """
        fusion = next(
            (f for f in reversed(self.fusions) if f.target == target), None
        )
        if fusion is None or fusion.source in self.voice:
            return None
        gardee = self.voice.get(target)
        if gardee is None:
            return None
        rendue = LiveVoice(
            identifier=fusion.source, name=fusion.name,
            certitude=fusion.certitude, rank=fusion.rank,
            voiceprints=list(fusion.voiceprints),
            likeness=fusion.likeness, gap=fusion.gap,
        )
        # Retirées par identité et non par valeur : deux extraits d'une même
        # voix peuvent porter le même vecteur, et un `remove` par égalité
        # emporterait celui de la cible.
        a_rendre = {id(e) for e in fusion.voiceprints}
        gardee.voiceprints = [e for e in gardee.voiceprints if id(e) not in a_rendre]
        gardee.forget_aggregate()
        # La cible retrouve ce qu'elle portait avant, sauf si un humain l'a
        # nommée depuis : sa décision est postérieure, elle l'emporte.
        if gardee.certitude is not Certainty.HUMAINE:
            gardee.name, gardee.certitude = fusion.nom_cible, fusion.certitude_cible
        for turn in self.turns:
            if turn.voice == target and turn.number in set(fusion.numeros):
                turn.voice = fusion.source
        self.voice[fusion.source] = rendue
        self.fusions.remove(fusion)
        self.split_apart.add(frozenset({fusion.source, target}))
        return fusion

    def _held_apart(self, une: str, autre: str) -> bool:
        """Vrai quand un humain a déjà dit que ces deux voix ne sont pas la même."""
        return frozenset({une, autre}) in self.split_apart

    def stitch(self) -> list[tuple[str, str]]:
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
        faits += self._join_namesakes()
        candidates = {
            identifier: voice.voiceprints
            for identifier, voice in self.voice.items()
            if voice.voiceprints and identifier not in (VOIX_LOCALE, VOIX_INDETERMINEE)
        }
        if len(candidates) < 2:
            return faits
        for source, target in join_voices(candidates).items():
            if source == target or source not in self.voice or target not in self.voice:
                continue
            if self._different_human_names(source, target):
                continue
            if self._held_apart(source, target):
                continue
            self._absorb(source, target)
            faits.append((source, target))
        return faits

    def _join_namesakes(self) -> list[tuple[str, str]]:
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
        by_name: dict[str, list[LiveVoice]] = {}
        for voice in self.voice.values():
            if voice.name and voice.nameable and voice.identifier != VOIX_LOCALE:
                by_name.setdefault(voice.name.casefold(), []).append(voice)
        faits: list[tuple[str, str]] = []
        for portantes in by_name.values():
            if len(portantes) < 2:
                continue
            # La plus fournie garde son identifiant : c'est celle dont l'extrait
            # est le plus représentatif, et celle que l'oeil a le plus vue.
            portantes.sort(key=lambda v: -v.seconds)
            gardee = portantes[0]
            for absorbee in portantes[1:]:
                if self._held_apart(absorbee.identifier, gardee.identifier):
                    continue
                self._absorb(absorbee.identifier, gardee.identifier)
                faits.append((absorbee.identifier, gardee.identifier))
        return faits

    def _different_human_names(self, un: str, autre: str) -> bool:
        premier, second = self.voice[un], self.voice[autre]
        return (
            premier.certitude is Certainty.HUMAINE
            and second.certitude is Certainty.HUMAINE
            and premier.name != second.name
        )

    def _correct_the_sentence(self, turn: LiveTurn, name: str) -> Correction:
        """Déplace une seule phrase, sans toucher au reste de la voix.

        La phrase rejoint la voix qui porte déjà ce nom si elle existe, pour que
        les tours de la même personne restent d'un seul tenant. Aucune empreinte
        n'est versée à la banque : le passage vient d'un groupe dont on vient
        justement de dire qu'il était mal formé.
        """
        target = self._voice_named(name)
        if target is None:
            target = LiveVoice(
                identifier=self._identifier(), name=name,
                certitude=Certainty.HUMAINE, rank=self._rank(),
            )
            self.voice[target.identifier] = target
        turn.voice = target.identifier
        return Correction(name=name, voice=target.identifier,
                          numeros=(turn.number,), whole_voice=False)

    def voiceprint_to_learn(self, voice: LiveVoice) -> Voiceprint | None:
        """L'empreinte à verser en banque pour cette voix, s'il y a de quoi.

        Rien pour la personne qui enregistre : son micro la nomme, et ranger sa
        voix parmi les participants ne servirait qu'à l'exposer. Rien non plus
        sous le seuil de matière : une signature apprise sur trois secondes de
        « d'accord » abîmerait la reconnaissance des réunions suivantes.
        """
        if voice.identifier == VOIX_LOCALE or not voice.voiceprints:
            return None
        if voice.seconds < DUREE_POUR_LA_BANQUE_S:
            return None
        return voice.aggregate_of

    def reserve_identifier(self, identifier: str) -> None:
        """Avance le compteur au-delà d'un identifiant venu d'ailleurs.

        Le journal nomme les voix « v1 », « v2 »… Les rejouer sans avancer le
        compteur lui fait redistribuer « v1 », qui **écrase** alors la voix
        existante : deux personnes sous un même identifiant, sans rien qui le
        signale. Le cas se produit à chaque reprise de fil.
        """
        if len(identifier) < 2 or identifier[0] != "v":
            return
        chiffres = identifier[1:]
        if chiffres.isdigit():
            self.suite = max(self.suite, int(chiffres))

    def _identifier(self) -> str:
        self.suite += 1
        # La ceinture, en plus de `retenir_l_identifiant` : un identifiant déjà
        # pris ne doit jamais ressortir, quelle que soit la façon dont la voix
        # est entrée dans le fil.
        while f"v{self.suite}" in self.voice:
            self.suite += 1
        return f"v{self.suite}"

    def _rank(self) -> int:
        """Numéro d'affichage d'une voix sans nom : « Voix 1 », « Voix 2 »…

        La personne qui enregistre n'y figure pas : son micro la nomme déjà.
        """
        return sum(
            1 for v in self.voice.values()
            if v.nameable and v.identifier != VOIX_LOCALE
        ) + 1

    def _voice_named(self, name: str) -> LiveVoice | None:
        replie = name.casefold()
        for voice in self.voice.values():
            if voice.name is not None and voice.name.casefold() == replie:
                return voice
        return None

    def _turn(self, number: int) -> LiveTurn:
        for turn in self.turns:
            if turn.number == number:
                return turn
        raise KeyError(f"aucune phrase numéro {number} dans le fil")
