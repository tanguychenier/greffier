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

from greffier.domaine.langue import ProfilLinguistique
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole, TypeMention

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
    profil: ProfilLinguistique,
    exclus: frozenset[str] | None = None,
) -> list[Mention]:
    """Relève tous les noms prononcés et ce qu'ils désignent.

    Les motifs se recouvrent volontiers (« Marc, tu peux » attrape aussi
    « c'est Marc ») : une même position dans le texte ne produit qu'une mention,
    celle du motif le plus fort.

    Le profil est exigé, sans valeur par défaut : supposer le français a un coût
    mesuré. Ses motifs appliqués à de l'anglais ne restent pas muets, ils
    rendent « Budget » et « Anyway » sur des phrases ordinaires. Une langue sans
    profil éprouvé n'a donc aucune détection, et ne rend rien.
    """
    if not profil.detection.active:
        return []
    interdits = profil.detection.exclus | (exclus or frozenset()) | _mots_communs(repliques)
    francs = [(t, m) for t, m, confirmation in profil.detection.motifs if not confirmation]
    larges = [(t, m) for t, m, confirmation in profil.detection.motifs if confirmation]

    # Première passe : les motifs francs établissent qui existe. Seconde passe :
    # les motifs larges n'ajoutent des indices que sur ces noms-là.
    mentions = _passe(repliques, francs, interdits, None, profil)
    connus = {m.clef for m in mentions}
    mentions += _passe(repliques, larges, interdits, connus, profil)
    return sorted(mentions, key=lambda m: m.instant)


def _passe(
    repliques: list[Replique],
    motifs: list[tuple[TypeMention, re.Pattern[str]]],
    interdits: frozenset[str],
    connus: set[str] | None,
    profil: ProfilLinguistique,
) -> list[Mention]:
    mentions: list[Mention] = []
    for replique in repliques:
        vues: dict[tuple[int, str], Mention] = {}
        for type_mention, motif in motifs:
            for trouve in motif.finditer(replique.texte):
                nom = trouve.group("nom")
                if _sans_accent(nom) in interdits or len(nom) < profil.detection.longueur_minimale:
                    continue
                # Le suffixe adverbial que la langue déclare, s'il en a un : en
                # français, les adverbes en « -ment » ouvrent d'innombrables
                # phrases et aucun n'a moins de huit lettres, ce qui épargne
                # « Clément ». Une langue qui n'en déclare pas ne filtre rien.
                depouille = _sans_accent(nom)
                suffixe = profil.detection.suffixe_adverbial
                if (
                    suffixe
                    and len(depouille) >= profil.detection.longueur_du_suffixe
                    and depouille.endswith(suffixe)
                ):
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


def reunir_les_homonymes(
    noms: dict[str, str], poids: dict[str, float]
) -> dict[str, str]:
    """Deux voix que l'on nomme pareil sont la même personne.

    L'information est déjà là et ne coûte rien : quand la chaîne conclut
    « Lise » sur sept voix distinctes, elle a déjà dit que ces sept voix sont
    de Lise. Attendre que leurs empreintes se ressemblent assez pour être
    recollées, c'est refuser ce qu'on tient — et le compte rendu annonce alors
    sept participants de plus.

    Mesuré sur une réunion réelle de 1 h 42 : **« Lise » sur sept voix**, dont
    six d'un seul tour de parole. La même règle existait déjà pour le direct ;
    elle manquait à la chaîne d'après réunion.

    La voix la plus fournie l'emporte : c'est celle dont l'extrait est le plus
    représentatif, et celle que la banque de voix a le plus de raisons d'avoir
    reconnue. Rend l'appartenance de chaque voix, y compris celles qui ne
    bougent pas.
    """
    portantes: dict[str, list[str]] = {}
    for voix, nom in noms.items():
        replie = _sans_accent(nom.strip().casefold())
        if replie:
            portantes.setdefault(replie, []).append(voix)
    appartenance = {voix: voix for voix in noms}
    for ensemble in portantes.values():
        if len(ensemble) < 2:
            continue
        gardee = max(ensemble, key=lambda v: (poids.get(v, 0.0), v))
        for voix in ensemble:
            appartenance[voix] = gardee
    return appartenance
