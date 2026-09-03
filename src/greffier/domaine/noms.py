"""Retrouver le nom des participants dans ce qu'ils disent.

Personne n'est prié de se présenter : en réunion, les gens se nomment
naturellement. Trois façons, qui ne désignent pas la même personne — d'où la
distinction faite ici :

    « moi c'est Tanguy »          → celui qui parle
    « Josiane, tu peux nous dire » → celui qui va parler
    « merci Marc »                 → celui qui vient de parler

Aucune de ces mentions ne suffit seule : « merci Marc » peut être dit par Marc,
et whisper écorche les noms propres. On accumule donc les indices sur toute la
réunion et on compte. Ce qui dépasse le seuil est tenu pour acquis ; le reste
est proposé à l'utilisateur, jamais affirmé.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from greffier.domaine.modeles import Intervalle, Replique, TourDeParole


class TypeMention(StrEnum):
    """Qui la mention désigne, relativement à celui qui la prononce."""

    AUTO_PRESENTATION = "auto_presentation"   # le locuteur courant
    INTERPELLATION = "interpellation"         # le locuteur suivant
    RENVOI = "renvoi"                         # le locuteur précédent


# Une auto-présentation est presque toujours juste : c'est l'intéressé qui
# parle. Une interpellation l'est souvent. Un renvoi (« merci Marc ») est le
# plus fragile — il peut viser quelqu'un qui a parlé bien avant.
POIDS: dict[TypeMention, int] = {
    TypeMention.AUTO_PRESENTATION: 3,
    TypeMention.INTERPELLATION: 2,
    TypeMention.RENVOI: 1,
}

# Fenêtres de recherche du locuteur visé, en secondes. Au-delà, le lien entre
# la mention et le tour de parole devient trop lâche pour compter.
FENETRE_SUIVANT = 30.0
FENETRE_PRECEDENT = 60.0

# Un nom propre commence par une majuscule — whisper les restitue ainsi. Les
# mots déclencheurs, eux, sont insensibles à la casse : « Merci » en début de
# phrase et « merci » au fil de l'eau désignent la même chose. D'où les
# drapeaux locaux « (?i:…) », qui laissent la contrainte de majuscule intacte
# sur le nom lui-même.
_NOM = r"(?P<nom>[A-ZÉÈÊÀÂÎÔÛÇ][\w'’-]{1,19})"

# Troisième membre : « confirmation seule ». Un tel motif est trop large pour
# désigner un prénom à lui seul — il ne compte que si le nom a déjà été repéré
# par un motif franc ailleurs dans la réunion.
_MOTIFS: list[tuple[TypeMention, re.Pattern[str], bool]] = [
    # --- le locuteur se nomme lui-même ---
    (TypeMention.AUTO_PRESENTATION, re.compile(
        r"(?i:\bje m['’]appelle|\bmoi,? c['’]est)\s+" + _NOM
    ), False),
    # « c'est Marc » tout court désignerait n'importe qui : on exige la formule
    # complète, sans quoi une phrase à propos d'un absent le ferait participant.
    (TypeMention.AUTO_PRESENTATION, re.compile(
        r"(?i:\bc['’]est)\s+" + _NOM + r"\s+(?i:qui\s+(?:vous\s+)?parle)"
    ), False),
    (TypeMention.AUTO_PRESENTATION, re.compile(
        r"(?i:\bje suis)\s+" + _NOM + r"\b"
    ), False),
    (TypeMention.AUTO_PRESENTATION, re.compile(
        _NOM + r"\s*,?\s*(?i:à l['’]appareil)"
    ), False),
    # --- le locuteur passe la parole à quelqu'un ---
    # « tu vois », « tu sais », « vous voyez » sont des tics de langage, pas des
    # adresses : sans cette exception, « un macro Kanban, tu vois » ferait de
    # Kanban un participant. Constaté sur une vraie réunion.
    (TypeMention.INTERPELLATION, re.compile(
        _NOM + r"\s*,\s*(?:(?i:tu|vous)\s+(?!(?i:vois|voyez|sais|savez)\b)"
        r"|(?i:est-ce que\b|peux-tu\b|pouvez-vous\b|qu['’]en penses|qu['’]en pensez))"
    ), False),
    (TypeMention.INTERPELLATION, re.compile(
        r"(?i:\bvas-y|\ballez-y|\bà toi|\bje te laisse|\bje vous laisse"
        r"|\bje passe la parole à|\bla parole (?:est )?à)\s+" + _NOM + r"\b"
    ), False),
    # --- le locuteur renvoie à celui qui vient de parler ---
    (TypeMention.RENVOI, re.compile(
        r"(?i:\bmerci)\s+" + _NOM + r"\b"
    ), False),
    (TypeMention.RENVOI, re.compile(
        r"(?i:\bcomme (?:le |l['’])?(?:disait|dit|a dit)|\bd['’]accord avec"
        r"|\bje rejoins|\bje suis d['’]accord avec)\s+" + _NOM + r"\b"
    ), False),
    (TypeMention.RENVOI, re.compile(
        _NOM + r"\s+(?i:a raison|vient de (?:le )?dire|l['’]a dit)\b"
    ), False),
    # --- formulations relevées sur de vraies réunions ---
    # « Mais pour ça, toi, Josiane, c'est pas besoin ? »
    (TypeMention.INTERPELLATION, re.compile(
        r"(?i:\btoi)\s*,\s*" + _NOM + r"\b"
    ), False),
    # « Josiane, on a lu ensemble et tu nous diras » : un nom en tête de phrase
    # n'est un appel que si une adresse suit. L'anticipation évite de prendre
    # pour un prénom le premier mot capitalisé venu.
    (TypeMention.INTERPELLATION, re.compile(
        r"(?:^|(?<=[.?!]\s))" + _NOM + r"\s*,\s*(?=[^.?!]{0,60}?\b(?i:tu|vous|on)\b)"
    ), False),
    # Un segment réduit au seul mot : « Josiane. » appelle quelqu'un, mais
    # « Ouais. » et « Exact. » aussi passeraient. D'où la confirmation seule —
    # relevé sur la réunion du 2026-08-20, où ce motif ramassait tous les
    # acquiescements.
    (TypeMention.INTERPELLATION, re.compile(
        r"^" + _NOM + r"\s*[,.?!]?\s*$"
    ), True),
    # « pour ce que présentait Josiane »
    (TypeMention.RENVOI, re.compile(
        r"(?i:\bqu[e\u2019']\s*(?:présentait|présente|disait|expliquait|proposait"
        r"|évoquait|montrait|a présenté|a dit))\s+" + _NOM + r"\b"
    ), False),
]

# Mots qui passent les motifs sans être des noms de personne. Le vocabulaire
# métier du projet s'y ajoute par configuration : sans quoi « merci Copernic »
# créerait un participant.
EXCLUS_PAR_DEFAUT: frozenset[str] = frozenset({
    # Ouvertures de phrase : un mot capitalisé en tête n'est pas un prénom.
    "mais", "bon", "bref", "ensuite", "enfin", "ecoute", "ecoutez", "attends",
    "ok", "ah", "eh", "euh", "apres", "avant", "sinon", "sur", "dans", "les",
    "est", "peut", "parce", "pourquoi", "comment", "quand", "moi", "toi", "lui",
    "elle", "nous", "vous", "ils", "elles", "ca", "cela", "ceci", "celui",
    "effectivement", "exactement", "super", "parfait", "tres", "plus", "moins",
    # Interjections et impératifs d'attention : « Tiens, tu as vu ? » a été pris
    # pour un prénom sur une vraie réunion.
    "tiens", "tenez", "regarde", "regardez", "voyons", "allez", "vas",
    "dis", "dites", "figure", "imagine", "franchement", "honnetement",
    "petit", "grand", "aujourd'hui", "hier", "demain", "pareil", "pardon", "desole",
    "bonjour", "bonsoir", "merci", "oui", "non", "voila", "donc", "alors",
    "monsieur", "madame", "tout", "tous", "toute", "toutes", "beaucoup",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
    "septembre", "octobre", "novembre", "decembre",
    "teams", "zoom", "jira", "gitlab", "outlook", "claude", "mac", "windows",
    "france", "paris", "saclay", "centralesupelec", "universite",
})


def _sans_accent(mot: str) -> str:
    depouille = unicodedata.normalize("NFD", mot.replace("’", "'"))
    return "".join(c for c in depouille if unicodedata.category(c) != "Mn").lower()


@dataclass(frozen=True, slots=True)
class Mention:
    """Un nom prononcé, situé dans le temps, et ce qu'il désigne.

    On retient l'intervalle de la réplique entière, et non l'instant où le nom
    tombe : les bornes de la transcription et celles de la segmentation ne
    coïncident jamais exactement. Une réplique commençant à 00:00,00 alors que
    la parole n'est détectée qu'à 00:00,30 tombait dans un trou et ne désignait
    personne — constaté sur une réunion de synthèse.
    """

    nom: str
    intervalle: Intervalle
    type: TypeMention
    extrait: str

    @property
    def instant(self) -> float:
        return self.intervalle.debut

    @property
    def clef(self) -> str:
        """Forme normalisée, pour que « Josiane » et « josiane » comptent ensemble."""
        return _sans_accent(self.nom)


@dataclass(slots=True)
class Attribution:
    """Ce qu'on croit savoir d'une voix, et sur quelles bases."""

    voix: str
    nom: str
    score: int
    indices: list[Mention] = field(default_factory=list)
    concurrent: str | None = None      # deuxième nom le mieux placé, s'il existe
    score_concurrent: int = 0

    @property
    def certaine(self) -> bool:
        """Assez d'indices concordants, d'origines différentes, et sans rival.

        Le score seul ne suffit pas : trois interpellations en valent six, ce qui
        franchit tous les seuils, et pourtant elles peuvent toutes désigner la
        même personne absente. Une interpellation vise **celui qui va parler** ;
        si l'interpellé ne répond jamais, chaque mention se reporte sur le
        locuteur suivant, et les indices s'empilent sur la mauvaise voix.

        C'est arrivé : sur une réunion d'une heure, une personne a été
        interpellée trois fois sans jamais décrocher un mot. Son prénom s'est vu
        attribuer, de façon ferme, la voix qui totalisait 64 % du temps de parole.

        La distinction est dans la direction de l'indice. Une auto-présentation
        et un renvoi (« merci Marc ») visent le passé ou le présent : quelqu'un a
        parlé, on sait qui. Une interpellation vise l'avenir, et l'avenir peut ne
        pas venir. Un nom qui ne repose que sur des interpellations reste donc
        **proposé**, jamais affirmé, quel qu'en soit le nombre.
        """
        if self.score < 3 or self.score < 2 * self.score_concurrent:
            return False
        types = {mention.type for mention in self.indices}
        return types != {TypeMention.INTERPELLATION}


@dataclass(slots=True)
class Resultat:
    certitudes: dict[str, Attribution] = field(default_factory=dict)
    propositions: list[Attribution] = field(default_factory=list)


_MOT = re.compile(r"[\w'’-]+")


def _mots_communs(repliques: list[Replique]) -> frozenset[str]:
    """Les mots que la réunion emploie aussi en minuscule : jamais des prénoms.

    Whisper met une majuscule à chaque début de phrase, et les motifs
    d'interpellation attrapent forcément des débuts de phrase. « Ouais »,
    « Bon », « Voilà », « Maintenant », « C'est-à-dire » se sont ainsi retrouvés
    candidats, et sur une réunion réelle « Ouais » a été promu prénom avec
    treize minutes de temps de parole.

    La transcription porte elle-même de quoi trancher : un mot courant apparaît
    tôt ou tard ailleurs, au milieu d'une phrase, en minuscule. Un prénom, non.
    Mesuré sur cette réunion : six des sept faux candidats écartés, aucun des
    sept vrais prénoms touché.

    Le seul angle mort est le nom propre qui n'est pas un prénom, un nom de
    ville par exemple, qui ne paraît jamais en minuscule non plus. Il reste
    candidat, et c'est à l'accumulation d'indices de le disqualifier.
    """
    minuscules: set[str] = set()
    for replique in repliques:
        for mot in _MOT.findall(replique.texte):
            if mot[:1].islower():
                minuscules.add(_sans_accent(mot))
    return frozenset(minuscules)


def reperer_mentions(
    repliques: list[Replique],
    exclus: frozenset[str] | None = None,
) -> list[Mention]:
    """Relève tous les noms prononcés et ce qu'ils désignent.

    Les motifs se recouvrent volontiers (« Marc, tu peux » attrape aussi
    « c'est Marc ») : une même position dans le texte ne produit qu'une mention,
    celle du motif le plus fort.
    """
    interdits = EXCLUS_PAR_DEFAUT | (exclus or frozenset()) | _mots_communs(repliques)
    francs = [(t, m) for t, m, confirmation in _MOTIFS if not confirmation]
    larges = [(t, m) for t, m, confirmation in _MOTIFS if confirmation]

    # Première passe : les motifs francs établissent qui existe. Seconde passe :
    # les motifs larges n'ajoutent des indices que sur ces noms-là.
    mentions = _passe(repliques, francs, interdits, None)
    connus = {m.clef for m in mentions}
    mentions += _passe(repliques, larges, interdits, connus)
    return sorted(mentions, key=lambda m: m.instant)


def _passe(
    repliques: list[Replique],
    motifs: list[tuple[TypeMention, re.Pattern[str]]],
    interdits: frozenset[str],
    connus: set[str] | None,
) -> list[Mention]:
    mentions: list[Mention] = []
    for replique in repliques:
        vues: dict[tuple[int, str], Mention] = {}
        for type_mention, motif in motifs:
            for trouve in motif.finditer(replique.texte):
                nom = trouve.group("nom")
                if _sans_accent(nom) in interdits or len(nom) < 3:
                    continue
                # Les adverbes en « -ment » ouvrent d'innombrables phrases —
                # « Effectivement, tu as raison », « Normalement, on livre jeudi » —
                # et aucun n'a moins de huit lettres. Le seuil épargne « Clément »,
                # à peu près le seul prénom français de cette forme.
                depouille = _sans_accent(nom)
                if len(depouille) >= 8 and depouille.endswith("ment"):
                    continue
                if connus is not None and _sans_accent(nom) not in connus:
                    continue
                position = trouve.start("nom")
                clef = (position, _sans_accent(nom))
                candidate = Mention(
                    nom=nom,
                    intervalle=replique.intervalle,
                    type=type_mention,
                    extrait=replique.texte.strip(),
                )
                ancienne = vues.get(clef)
                if ancienne is None or POIDS[type_mention] > POIDS[ancienne.type]:
                    vues[clef] = candidate
        mentions.extend(vues.values())
    return mentions


# Tolérance de rattachement quand une réplique ne recouvre aucun tour : les
# bornes de la transcription et de la segmentation diffèrent toujours un peu.
ECART_TOLERE = 3.0


def _voix_pendant(intervalle: Intervalle, tours: list[TourDeParole]) -> str | None:
    """Voix qui parle le plus pendant la réplique.

    Par recouvrement plutôt que par instant : c'est la même règle que pour
    attribuer une réplique à un locuteur, et elle ne dépend pas de la précision
    au centième de seconde des deux modèles.
    """
    cumuls: dict[str, float] = {}
    for tour in tours:
        commun = intervalle.recouvrement(tour.intervalle)
        if commun > 0:
            cumuls[tour.voix] = cumuls.get(tour.voix, 0.0) + commun
    if cumuls:
        return max(cumuls, key=lambda v: cumuls[v])
    # Aucun recouvrement : on rattache au tour le plus proche, s'il l'est assez.
    proche = min(
        tours,
        key=lambda t: min(abs(t.intervalle.debut - intervalle.fin),
                          abs(intervalle.debut - t.intervalle.fin)),
        default=None,
    )
    if proche is None:
        return None
    ecart = min(abs(proche.intervalle.debut - intervalle.fin),
                abs(intervalle.debut - proche.intervalle.fin))
    return proche.voix if ecart <= ECART_TOLERE else None


def _voix_suivante(instant: float, courante: str | None, tours: list[TourDeParole]) -> str | None:
    for tour in tours:
        if tour.intervalle.debut > instant and tour.voix != courante:
            return tour.voix if tour.intervalle.debut - instant <= FENETRE_SUIVANT else None
    return None


def _voix_precedente(instant: float, courante: str | None, tours: list[TourDeParole]) -> str | None:
    candidat: TourDeParole | None = None
    for tour in tours:
        if tour.intervalle.fin <= instant and tour.voix != courante:
            candidat = tour
    if candidat is None:
        return None
    return candidat.voix if instant - candidat.intervalle.fin <= FENETRE_PRECEDENT else None


def cible(mention: Mention, tours: list[TourDeParole]) -> str | None:
    """La voix que cette mention désigne, selon sa nature."""
    courante = _voix_pendant(mention.intervalle, tours)
    match mention.type:
        case TypeMention.AUTO_PRESENTATION:
            return courante
        case TypeMention.INTERPELLATION:
            return _voix_suivante(mention.instant, courante, tours)
        case TypeMention.RENVOI:
            return _voix_precedente(mention.instant, courante, tours)


def attribuer(mentions: list[Mention], tours: list[TourDeParole]) -> Resultat:
    """Rapproche les noms prononcés des voix, par accumulation d'indices.

    Un nom ne peut désigner qu'une voix : si deux voix se disputent le même nom,
    seule la mieux étayée le garde, l'autre repasse en proposition. Sans cette
    règle, un « merci Marc » égaré suffirait à baptiser deux personnes Marc.
    """
    scores: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    indices: dict[tuple[str, str], list[Mention]] = defaultdict(list)

    for mention in mentions:
        voix = cible(mention, tours)
        if voix is None:
            continue
        scores[voix][mention.nom] += POIDS[mention.type]
        indices[(voix, mention.nom)].append(mention)

    candidats: list[Attribution] = []
    for voix, par_nom in scores.items():
        classement = sorted(par_nom.items(), key=lambda x: (-x[1], x[0]))
        meilleur, score = classement[0]
        second, score_second = classement[1] if len(classement) > 1 else (None, 0)
        candidats.append(Attribution(
            voix=voix, nom=meilleur, score=score,
            indices=indices[(voix, meilleur)],
            concurrent=second, score_concurrent=score_second,
        ))

    resultat = Resultat()
    pris: dict[str, Attribution] = {}
    for attribution in sorted(candidats, key=lambda a: -a.score):
        if not attribution.certaine:
            resultat.propositions.append(attribution)
            continue
        tenant = pris.get(_sans_accent(attribution.nom))
        if tenant is None:
            pris[_sans_accent(attribution.nom)] = attribution
            resultat.certitudes[attribution.voix] = attribution
        else:
            resultat.propositions.append(attribution)

    resultat.propositions.sort(key=lambda a: -a.score)
    return resultat
