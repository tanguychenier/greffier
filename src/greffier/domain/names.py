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

from greffier.domain.language import LanguageProfile
from greffier.domain.models import MentionKind, Span, SpeakerTurn, Utterance

# Une auto-présentation est presque toujours juste : c'est l'intéressé qui
# parle. Une interpellation l'est souvent. Un renvoi (« merci Marc ») est le
# plus fragile — il peut viser quelqu'un qui a parlé bien avant.
POIDS: dict[MentionKind, int] = {
    MentionKind.AUTO_PRESENTATION: 3,
    MentionKind.INTERPELLATION: 2,
    MentionKind.RENVOI: 1,
}

# Fenêtres de recherche du locuteur visé, en secondes. Au-delà, le lien entre
# la mention et le tour de parole devient trop lâche pour compter.
FENETRE_SUIVANT = 30.0
FENETRE_PRECEDENT = 60.0

def _without_accents(mot: str) -> str:
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

    name: str
    span: Span
    type: MentionKind
    extrait: str

    @property
    def at_instant(self) -> float:
        return self.span.start

    @property
    def key(self) -> str:
        """Forme normalisée, pour que « Josiane » et « josiane » comptent ensemble."""
        return _without_accents(self.name)


@dataclass(slots=True)
class Attribution:
    """Ce qu'on croit savoir d'une voix, et sur quelles bases."""

    voice: str
    name: str
    score: int
    indices: list[Mention] = field(default_factory=list)
    concurrent: str | None = None      # deuxième nom le mieux placé, s'il existe
    score_concurrent: int = 0

    @property
    def certain(self) -> bool:
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
        return types != {MentionKind.INTERPELLATION}


@dataclass(slots=True)
class Outcome:
    certitudes: dict[str, Attribution] = field(default_factory=dict)
    propositions: list[Attribution] = field(default_factory=list)


_MOT = re.compile(r"[\w'’-]+")


def _common_words(utterances: list[Utterance]) -> frozenset[str]:
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
    for utterance in utterances:
        for mot in _MOT.findall(utterance.text):
            if mot[:1].islower():
                minuscules.add(_without_accents(mot))
    return frozenset(minuscules)


def spot_mentions(
    utterances: list[Utterance],
    profil: LanguageProfile,
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
    interdits = profil.detection.exclus | (exclus or frozenset()) | _common_words(utterances)
    francs = [(t, m) for t, m, confirmation in profil.detection.motifs if not confirmation]
    larges = [(t, m) for t, m, confirmation in profil.detection.motifs if confirmation]

    # Première passe : les motifs francs établissent qui existe. Seconde passe :
    # les motifs larges n'ajoutent des indices que sur ces noms-là.
    mentions = _passe(utterances, francs, interdits, None, profil)
    known = {m.key for m in mentions}
    mentions += _passe(utterances, larges, interdits, known, profil)
    return sorted(mentions, key=lambda m: m.at_instant)


def _passe(
    utterances: list[Utterance],
    motifs: list[tuple[MentionKind, re.Pattern[str]]],
    interdits: frozenset[str],
    known: set[str] | None,
    profil: LanguageProfile,
) -> list[Mention]:
    mentions: list[Mention] = []
    for utterance in utterances:
        vues: dict[tuple[int, str], Mention] = {}
        for type_mention, motif in motifs:
            for trouve in motif.finditer(utterance.text):
                name = trouve.group("nom")
                if (_without_accents(name) in interdits
                or len(name) < profil.detection.longueur_minimale):
                    continue
                # Le suffixe adverbial que la langue déclare, s'il en a un : en
                # français, les adverbes en « -ment » ouvrent d'innombrables
                # phrases et aucun n'a moins de huit lettres, ce qui épargne
                # « Clément ». Une langue qui n'en déclare pas ne filtre rien.
                depouille = _without_accents(name)
                suffixe = profil.detection.suffixe_adverbial
                if (
                    suffixe
                    and len(depouille) >= profil.detection.longueur_du_suffixe
                    and depouille.endswith(suffixe)
                ):
                    continue
                if known is not None and _without_accents(name) not in known:
                    continue
                position = trouve.start("nom")
                key = (position, _without_accents(name))
                candidate = Mention(
                    name=name,
                    span=utterance.span,
                    type=type_mention,
                    extrait=utterance.text.strip(),
                )
                ancienne = vues.get(key)
                if ancienne is None or POIDS[type_mention] > POIDS[ancienne.type]:
                    vues[key] = candidate
        mentions.extend(vues.values())
    return mentions


# Tolérance de rattachement quand une réplique ne recouvre aucun tour : les
# bornes de la transcription et de la segmentation diffèrent toujours un peu.
ECART_TOLERE = 3.0


def _voice_during(span: Span, turns: list[SpeakerTurn]) -> str | None:
    """Voix qui parle le plus pendant la réplique.

    Par recouvrement plutôt que par instant : c'est la même règle que pour
    attribuer une réplique à un locuteur, et elle ne dépend pas de la précision
    au centième de seconde des deux modèles.
    """
    cumuls: dict[str, float] = {}
    for turn in turns:
        commun = span.overlap(turn.span)
        if commun > 0:
            cumuls[turn.voice] = cumuls.get(turn.voice, 0.0) + commun
    if cumuls:
        return max(cumuls, key=lambda v: cumuls[v])
    # Aucun recouvrement : on rattache au tour le plus proche, s'il l'est assez.
    proche = min(
        turns,
        key=lambda t: min(abs(t.span.start - span.end),
                          abs(span.start - t.span.end)),
        default=None,
    )
    if proche is None:
        return None
    gap = min(abs(proche.span.start - span.end),
                abs(span.start - proche.span.end))
    return proche.voice if gap <= ECART_TOLERE else None


def _next_voice(at_instant: float, courante: str | None, turns: list[SpeakerTurn]) -> str | None:
    for turn in turns:
        if turn.span.start > at_instant and turn.voice != courante:
            return turn.voice if turn.span.start - at_instant <= FENETRE_SUIVANT else None
    return None


def _previous_voice(
    at_instant: float, courante: str | None, turns: list[SpeakerTurn]
) -> str | None:
    candidat: SpeakerTurn | None = None
    for turn in turns:
        if turn.span.end <= at_instant and turn.voice != courante:
            candidat = turn
    if candidat is None:
        return None
    return candidat.voice if at_instant - candidat.span.end <= FENETRE_PRECEDENT else None


def target(mention: Mention, turns: list[SpeakerTurn]) -> str | None:
    """La voix que cette mention désigne, selon sa nature."""
    courante = _voice_during(mention.span, turns)
    match mention.type:
        case MentionKind.AUTO_PRESENTATION:
            return courante
        case MentionKind.INTERPELLATION:
            return _next_voice(mention.at_instant, courante, turns)
        case MentionKind.RENVOI:
            return _previous_voice(mention.at_instant, courante, turns)


def attribute(mentions: list[Mention], turns: list[SpeakerTurn]) -> Outcome:
    """Rapproche les noms prononcés des voix, par accumulation d'indices.

    Un nom ne peut désigner qu'une voix : si deux voix se disputent le même nom,
    seule la mieux étayée le garde, l'autre repasse en proposition. Sans cette
    règle, un « merci Marc » égaré suffirait à baptiser deux personnes Marc.
    """
    scores: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    indices: dict[tuple[str, str], list[Mention]] = defaultdict(list)

    for mention in mentions:
        voice = target(mention, turns)
        if voice is None:
            continue
        scores[voice][mention.name] += POIDS[mention.type]
        indices[(voice, mention.name)].append(mention)

    candidats: list[Attribution] = []
    for voice, by_name in scores.items():
        ranking = sorted(by_name.items(), key=lambda x: (-x[1], x[0]))
        best, score = ranking[0]
        second, score_second = ranking[1] if len(ranking) > 1 else (None, 0)
        candidats.append(Attribution(
            voice=voice, name=best, score=score,
            indices=indices[(voice, best)],
            concurrent=second, score_concurrent=score_second,
        ))

    outcome = Outcome()
    pris: dict[str, Attribution] = {}
    for attribution in sorted(candidats, key=lambda a: -a.score):
        if not attribution.certain:
            outcome.propositions.append(attribution)
            continue
        tenant = pris.get(_without_accents(attribution.name))
        if tenant is None:
            pris[_without_accents(attribution.name)] = attribution
            outcome.certitudes[attribution.voice] = attribution
        else:
            outcome.propositions.append(attribution)

    outcome.propositions.sort(key=lambda a: -a.score)
    return outcome


def join_namesakes(
    names: dict[str, str], poids: dict[str, float]
) -> dict[str, str]:
    """Deux voix que l'on nomme pareil sont la même personne.

    L'information est déjà là et ne coûte rien : quand la chaîne conclut
    « Laura » sur sept voix distinctes, elle a déjà dit que ces sept voix sont
    de Laura. Attendre que leurs empreintes se ressemblent assez pour être
    recollées, c'est refuser ce qu'on tient — et le compte rendu annonce alors
    sept participants de plus.

    Mesuré sur une réunion réelle de 1 h 42 : **« Laura » sur sept voix**, dont
    six d'un seul tour de parole. La même règle existait déjà pour le direct ;
    elle manquait à la chaîne d'après réunion.

    La voix la plus fournie l'emporte : c'est celle dont l'extrait est le plus
    représentatif, et celle que la banque de voix a le plus de raisons d'avoir
    reconnue. Rend l'appartenance de chaque voix, y compris celles qui ne
    bougent pas.
    """
    portantes: dict[str, list[str]] = {}
    for voice, name in names.items():
        replie = _without_accents(name.strip().casefold())
        if replie:
            portantes.setdefault(replie, []).append(voice)
    membership = {voice: voice for voice in names}
    for ensemble in portantes.values():
        if len(ensemble) < 2:
            continue
        gardee = max(ensemble, key=lambda v: (poids.get(v, 0.0), v))
        for voice in ensemble:
            membership[voice] = gardee
    return membership
