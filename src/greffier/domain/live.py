"""The meeting thread, while the meeting is happening.

What the full chain does afterwards — segment, group the voices, recognise the
people — is redone here slice by slice, on far less material. Conclusions are
therefore more fragile, and that is the point of this module: **it proposes, it
does not assert**, and it keeps track of what separates a certainty from a
guess.

Three sources of knowledge, most reliable first: a human correction, the
channel (a voice arriving on the mic belongs to whoever is recording), then the
voiceprint — useful, never sure.

Nothing here knows about whisper, sherpa or a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from greffier.domain.boilerplate import is_an_annotation, is_boilerplate
from greffier.domain.channels import LOCAL_VOICE
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
    """The words that carry meaning, each with where it ends in the text."""
    trouves: list[tuple[str, int]] = []
    for mot in _MOT_DIRECT.finditer(text):
        nu = mot.group().strip(_PONCTUATION_MOT).casefold()
        if nu:
            trouves.append((nu, mot.end()))
    return trouves

def _same_word(un: str, autre: str) -> bool:
    """Two transcriptions of one word: "l'ASIS" and "Oasis"."""
    if un == autre:
        return True
    plus_court = min(len(un), len(autre))
    if plus_court < 4:
        return False
    return distance(un, autre) <= (2 if plus_court >= 5 else 1)

def _overlap_each_other(gauche: list[str], droite: list[str]) -> bool:
    """True when these two word runs are the same passage, said twice."""
    if gauche == droite:
        return True
    if len(gauche) < MOTS_POUR_TOLERER:
        return False
    if not all(_same_word(a, b) for a, b in zip(gauche, droite, strict=True)):
        return False
    identiques = sum(1 for a, b in zip(gauche, droite, strict=True) if a == b)
    return identiques / len(gauche) >= PART_IDENTIQUE

def drop_repetition(precedent: str, nouveau: str) -> str:
    """Strips from the new text the tail the previous one already showed."""
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
    """Where the displayed name comes from. Decides what may be done with it.

    The order matters: a source can never be overwritten by a weaker one.
    """

    HUMAINE = "humaine"        # quelqu'un l'a corrigé à la main
    CANAL = "canal"            # le micro le dit : c'est toi
    RECONNUE = "reconnue"      # la banque de voix reconnaît, marge suffisante
    PROBABLE = "probable"      # au-dessus du seuil, mais peu de matière
    INCONNUE = "inconnue"      # aucune idée, et on le dit

    @property
    def firm(self) -> bool:
        """True once the name is no longer a guess."""
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
    """Consecutive utterances from one source.

    Attribution works on blocks rather than utterances: whisper cuts at the
    sentence, and a voiceprint taken from six words is worth nothing.
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
    """A voice as the thread knows it at this instant."""

    identifier: str
    name: str | None = None
    certitude: Certainty = Certainty.INCONNUE
    rank: int = 0
    voiceprints: list[Voiceprint] = field(default_factory=list)
    likeness: float = 0.0
    gap: float = 0.0

    _aggregate_of: Voiceprint | None = field(default=None, repr=False)

    def add(self, voiceprint: Voiceprint) -> None:
        """Pours in a voiceprint, and stales the aggregate."""
        self.voiceprints.append(voiceprint)
        self._aggregate_of = None

    def absorb(self, autre: LiveVoice) -> None:
        """Takes over another voice's voiceprints."""
        self.voiceprints.extend(autre.voiceprints)
        self._aggregate_of = None

    def forget_aggregate(self) -> None:
        """Stales the aggregate when the list changed without going through add."""
        self._aggregate_of = None

    @property
    def aggregate_of(self) -> Voiceprint:
        """The mean voiceprint of this voice, computed once per addition."""
        if self._aggregate_of is None:
            self._aggregate_of = aggregate(self.voiceprints)
        return self._aggregate_of

    @property
    def seconds(self) -> float:
        """Material gathered, to tell whether the voiceprint is worth keeping."""
        return sum(e.source_duration for e in self.voiceprints)

    @property
    def label(self) -> str:
        """What shows next to the sentence.

        The question mark is not decoration: it says the name comes from a voiceprint
        and awaits confirmation.
        """
        if self.name is None:
            return NOM_INDETERMINE if self.identifier == VOIX_INDETERMINEE else (
                f"Voix {self.rank}"
            )
        return self.name if self.certitude.firm else f"{self.name} ?"

    @property
    def confidence(self) -> str:
        """What the recognition is worth, in plain words. Empty when it did not play."""
        if self.name is None or not self.likeness:
            return ""
        if self.certitude is Certainty.HUMAINE:
            return "nommée à la main"
        if self.certitude is Certainty.CANAL:
            return "c'est ton micro"
        chiffres = f"ressemblance {self.likeness:.2f}, écart {self.gap:.2f}"
        if self.certitude is Certainty.RECONNUE:
            return f"reconnue nettement ({chiffres})"
        if self.gap < MARGE_LISIBLE:
            return f"proche d'une autre voix, à confirmer ({chiffres})"
        return f"probable, peu de matière ({chiffres})"

    @property
    def nameable(self) -> bool:
        """False for the catch-all of scraps: it mixes several people."""
        return self.identifier != VOIX_INDETERMINEE

@dataclass(slots=True)
class LiveTurn:
    """A displayed sentence, and who the thread attributes it to."""

    number: int
    span: Span
    text: str
    voice: str

@dataclass(frozen=True, slots=True)
class Correction:
    """What a human correction changed, for the caller to act on."""

    name: str
    voice: str
    numeros: tuple[int, ...]
    voiceprint: Voiceprint | None = None
    whole_voice: bool = True

def blocks(utterances: list[Utterance], locaux: list[Span]) -> list[Block]:
    """Groups utterances into passages from one source."""
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
    """What has to be kept in order to undo a join of two voices.

    Joining mixes the voiceprints into one heap and deletes the absorbed voice:
    without this record the mistake is permanent.
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
    """The thread of the meeting under way: what was said, and by whom.

    One object, held by the watching process. The window only sees the log it
    publishes, and sends corrections back.
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
            LOCAL_VOICE,
            LiveVoice(LOCAL_VOICE, name=NOM_LOCAL, certitude=Certainty.CANAL),
        )
        self.voice.setdefault(VOIX_INDETERMINEE, LiveVoice(VOIX_INDETERMINEE))

    def label(self, voice: str) -> str:
        connue = self.voice.get(voice)
        return connue.label if connue else f"Voix {voice}"

    def rendered(self, depuis: float = 0.0) -> str:
        """The thread as flowing attributed text, so that it can be questioned."""
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
        """The names a correction menu can offer without inventing anything."""
        vus = [v.name for v in self.voice.values() if v.name and v.name != NOM_LOCAL]
        for personne in self.connues:
            if personne.name not in vus:
                vus.append(personne.name)
        return [NOM_LOCAL, *vus]

    def retenir(self, utterances: list[Utterance]) -> list[Utterance]:
        """Discards what was already shown in the previous slice."""
        kept: list[Utterance] = []
        for utterance in utterances:
            if not utterance.text.strip():
                continue
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
            kept[0].text = drop_repetition(self.dernier_texte, kept[0].text)
        return kept

    def attach(self, voiceprint: Voiceprint | None, locale: bool) -> str:
        """The voice a block belongs to, founding one if need be."""
        if locale:
            return LOCAL_VOICE
        if voiceprint is None:
            return VOIX_INDETERMINEE

        proche = self._closest_voice(voiceprint)
        if proche is None and voiceprint.source_duration < MATIERE_MINIMALE_VOIX:
            proche = self._the_least_distant(voiceprint) or VOIX_INDETERMINEE
        if proche is None:
            proche = self._nearby_established_voice(voiceprint)
        if proche is None and len(self._nameable_ones()) >= VOIX_AU_PLUS:
            proche = self._the_least_distant(voiceprint)
        if proche is None and self._in_full():
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
        """The voices that name a person: neither "you" nor the catch-all."""
        return [
            voice for identifier, voice in self.voice.items()
            if identifier not in (LOCAL_VOICE, VOIX_INDETERMINEE) and voice.voiceprints
        ]

    def _in_full(self) -> bool:
        """True when as many voices exist as attendees were announced."""
        if not self.people:
            return False
        has_spoken = any(turn.voice == LOCAL_VOICE for turn in self.turns)
        distantes = self.people - (1 if has_spoken else 0)
        return len(self._nameable_ones()) >= max(1, distantes)

    def _the_least_distant(self, voiceprint: Voiceprint) -> str | None:
        """The most alike voice, threshold or not. Nothing if there is none."""
        ranking = sorted(
            ((similarity(voiceprint, v.aggregate_of), v.identifier)
             for v in self._nameable_ones()),
            key=lambda x: (-x[0], x[1]),
        )
        return ranking[0][1] if ranking else None

    def _nearby_established_voice(self, voiceprint: Voiceprint) -> str | None:
        """An **already well fed** voice this voiceprint joins without hesitation.

        The threshold is not enough on its own: it also has to clearly outrun the next
        best, otherwise the scrap belongs in the catch-all.
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
        """The voice of this meeting that most resembles, above the threshold."""
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
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if ranking[0][0] - second < MARGE_ADOPTION_DIRECT:
            return None
        return ranking[0][1]

    def _retenter_le_nom(self, voice: LiveVoice) -> None:
        """Asks the bank for a name again, now that there is more material."""
        if voice.certitude.firm or not voice.voiceprints:
            return
        if voice.seconds < MATIERE_POUR_RECONNAITRE:
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
        """Adds a block's sentences to the thread, attributed to a voice."""
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
        """Imposes a name, against what the voiceprint believed.

        By default the correction covers the **whole voice**: when the tool gets the
        person wrong, it gets them wrong for every passage of that voice.
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
        """Pours one voice into another: its turns, then its voiceprints.

        Records on the way what is needed to undo it.
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
        """Joins two voices while keeping what it takes to undo it."""
        if source == target or source not in self.voice or target not in self.voice:
            return None
        self._absorb(source, target)
        return self.fusions[-1]

    def can_split(self, target: str) -> bool:
        """True when this voice absorbed another one that can be taken back."""
        return any(
            f.target == target and f.source not in self.voice for f in self.fusions
        )

    def split(self, target: str) -> Join | None:
        """Undoes the last join that produced this voice.

        The absorbed voice takes back its identifier, its voiceprints and its turns,
        and the pair is held apart from then on.
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
        a_rendre = {id(e) for e in fusion.voiceprints}
        gardee.voiceprints = [e for e in gardee.voiceprints if id(e) not in a_rendre]
        gardee.forget_aggregate()
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
        """True when a human already said these two voices are not the same."""
        return frozenset({une, autre}) in self.split_apart

    def stitch(self) -> list[tuple[str, str]]:
        """Joins the voices that accumulated material shows to be one person.

        By pairs and not through the full stitching of the after-meeting chain: that
        one was measured here and dropped accuracy from 93% to 79.6%, which amounts to
        giving everything to the loudest voice.
        """
        faits: list[tuple[str, str]] = []
        faits += self._join_namesakes()
        candidates = {
            identifier: voice.voiceprints
            for identifier, voice in self.voice.items()
            if voice.voiceprints and identifier not in (LOCAL_VOICE, VOIX_INDETERMINEE)
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
        """Two voices the bank names alike are the same person.

        The self-correction that was missing, and it costs nothing: when the bank
        answers "Tanguy" on three separate voices, it has already said those three are
        Tanguy's.
        """
        by_name: dict[str, list[LiveVoice]] = {}
        for voice in self.voice.values():
            if voice.name and voice.nameable and voice.identifier != LOCAL_VOICE:
                by_name.setdefault(voice.name.casefold(), []).append(voice)
        faits: list[tuple[str, str]] = []
        for portantes in by_name.values():
            if len(portantes) < 2:
                continue
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
        """Moves a single sentence, without touching the rest of the voice."""
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
        """The voiceprint to pour into the bank for this voice, if there is enough."""
        if voice.identifier == LOCAL_VOICE or not voice.voiceprints:
            return None
        if voice.seconds < DUREE_POUR_LA_BANQUE_S:
            return None
        return voice.aggregate_of

    def reserve_identifier(self, identifier: str) -> None:
        """Advances the counter past an identifier that came from elsewhere.

        Replaying the log without this hands out "v1" again, which overwrites the
        existing voice: two people under one identifier, with nothing to signal it.
        """
        if len(identifier) < 2 or identifier[0] != "v":
            return
        chiffres = identifier[1:]
        if chiffres.isdigit():
            self.suite = max(self.suite, int(chiffres))

    def _identifier(self) -> str:
        self.suite += 1
        while f"v{self.suite}" in self.voice:
            self.suite += 1
        return f"v{self.suite}"

    def _rank(self) -> int:
        """Display number of an unnamed voice: "Voix 1", "Voix 2"…"""
        return sum(
            1 for v in self.voice.values()
            if v.nameable and v.identifier != LOCAL_VOICE
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
