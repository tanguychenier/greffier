"""Donner un nom à une voix, après la réunion.

C'est le chemin principal, et il est délibéré : **personne n'est prié de se
présenter**. On laisse la réunion se dérouler, puis on écoute dix secondes et on
tape un nom. Une seule fois par personne — ensuite l'empreinte est en banque et
la reconnaissance se fait seule.

Les noms prononcés pendant la réunion viennent en renfort, jamais en
remplacement : ils proposent, l'utilisateur tranche.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from greffier.domain import first_names
from greffier.domain import voiceprints as empreintes_domaine
from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span
from greffier.domain.voiceprints import aggregate
from greffier.ports import outbound

# Assez pour reconnaître une voix à l'oreille, assez court pour ne pas lasser
# quand il y a cinq personnes à nommer.
DUREE_EXTRAIT = 10.0
# En deçà, un passage ne porte pas assez de voix : ni pour l'oreille, ni pour
# l'empreinte.
DUREE_UTILE = 3.0

@dataclass
class VoixANommer:
    """Une voix de la réunion, telle qu'elle est présentée à l'utilisateur."""

    voice: str
    duration: float
    part: float
    name: str | None = None          # déjà nommée
    proposition: str | None = None  # nom deviné, à confirmer
    extrait: Span | None = None

    @property
    def to_name(self) -> bool:
        return self.name is None

def voices_to_name(meeting: StoredMeeting, minimum: float = 10.0) -> list[VoixANommer]:
    """Les voix de la réunion, de la plus bavarde à la moins, avec un extrait.

    Les fragments d'une seconde laissés par la segmentation sont écartés : les
    proposer à nommer ferait passer une réunion de cinq personnes pour une
    assemblée de vingt. Une voix courte qui porte déjà un nom ou une
    proposition détectée dans les mentions échappe à ce filtre : c'est
    justement le prénom prononcé dans une réponse brève qui se perdait sinon,
    jeté avec le fragment qui le portait.
    """
    temps = meeting.speaking_time()
    total = sum(d for d in temps.values() if d >= minimum) or 1.0
    outcome = []
    for voice, duration in temps.items():
        if duration < minimum and not (meeting.names.get(voice) or meeting.propositions.get(voice)):
            continue
        outcome.append(VoixANommer(
            voice=voice,
            duration=duration,
            part=duration / total,
            name=meeting.names.get(voice),
            proposition=meeting.propositions.get(voice),
            extrait=best_excerpt(meeting.spans_of(voice)),
        ))
    return outcome

def best_excerpt(intervalles: list[Span]) -> Span | None:
    """Le passage le plus représentatif à faire écouter.

    Le plus long tour de parole plutôt que le premier : un début de réunion
    commence souvent par un « oui, bonjour » qui ne dit rien du timbre.
    """
    utiles = [i for i in intervalles if i.duration >= DUREE_UTILE]
    if not utiles:
        utiles = intervalles
    if not utiles:
        return None
    plus_long = max(utiles, key=lambda i: i.duration)
    if plus_long.duration <= DUREE_EXTRAIT:
        return plus_long
    # Un peu après le début : on évite l'attaque, souvent hésitante.
    start = plus_long.start + min(1.0, (plus_long.duration - DUREE_EXTRAIT) / 2)
    return Span(start, start + DUREE_EXTRAIT)

def extract_audio(audio: Path, span: Span, destination: Path) -> Path:
    """Découpe un extrait, pour l'écouter."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{span.start:.3f}", "-t", f"{span.duration:.3f}",
         "-i", str(audio), "-c:a", "pcm_s16le", str(destination)],
        check=True,
    )
    return destination

@dataclass
class Naming:
    """Associe une voix à un nom, et fait entrer l'empreinte en banque."""

    store: outbound.MeetingStore
    bank: outbound.VoiceBank
    extractor: outbound.VoiceprintExtractor
    doute: str = ""

    def name_voice(self, identifier: str, voice: str, name: str) -> StoredMeeting:
        """Pose un nom sur une voix, et réunit celles qui portent déjà ce nom.

        Réunir, parce que c'est le geste qu'on fait sans le savoir : nommer
        « Marcel » une deuxième voix, c'est dire qu'elle est de Marcel, donc de
        la même personne. Sans cela, chaque voix gardait son identifiant et le
        compte rendu annonçait deux Marcel — sur une réunion réelle, trente-six
        voix ont été nommées à la main pour trois personnes présentes.
        """
        refuse = first_names.refusal(name)
        if refuse:
            raise ValueError(refuse)
        name = first_names.normalise(name)
        meeting = self.store.read(identifier)
        intervalles = meeting.spans_of(voice)
        if not intervalles:
            raise KeyError(
                f"La voix « {voice} » n'existe pas dans cette réunion. "
                f"Voix connues : {', '.join(sorted(meeting.speaking_time()))}"
            )
        voiceprints = self.extractor.extract_spans(meeting.audio, intervalles)
        if not voiceprints:
            raise ValueError(
                f"La voix « {voice} » n'a aucun passage d'au moins {DUREE_UTILE:.0f} s : "
                "trop peu de matière pour une empreinte fiable."
            )
        # Une empreinte agrégée sur toute la réunion, et non un extrait unique :
        # elle résiste mieux aux variations de posture et de distance au micro.
        # Avant de verser : cette voix ressemble-t-elle à quelqu'un d'autre ?
        # On ne refuse pas — deux collègues peuvent avoir des voix proches, et
        # l'utilisateur a le droit d'avoir raison contre la machine — mais on
        # ne laisse plus une entrée fausse entrer en silence.
        # L'origine voyage avec l'empreinte : c'est ce qui permettra de
        # défaire d'un geste ce qu'une réunion mal attribuée a versé.
        aggregate_of = replace(aggregate(voiceprints), origine=identifier)
        self.doute = empreintes_domaine.doubtful_entry(
            aggregate_of, name, self.bank.people())
        self.bank.record(name, aggregate_of)

        meeting.names[voice] = name
        meeting.propositions.pop(voice, None)
        # Les voix qui portaient déjà ce nom rejoignent celle-ci. La plus
        # fournie garde son identifiant : c'est celle dont l'extrait est le plus
        # représentatif si quelqu'un veut réécouter.
        temps = meeting.speaking_time()
        homonymes = [v for v in meeting.voice_named(name) if v != voice]
        for autre in homonymes:
            gardee, absorbee = (
                (voice, autre) if temps.get(voice, 0.0) >= temps.get(autre, 0.0)
                else (autre, voice)
            )
            meeting.join_into(absorbee, gardee)
            meeting.names[gardee] = name
            voice = gardee
        self.store.record(meeting)
        return meeting

    def forget(self, identifier: str, voice: str) -> StoredMeeting:
        """Retire le nom d'une voix, dans la réunion.

        Une erreur de nommage est le geste le plus coûteux de l'outil, et il
        n'était pas défaisable : on ne pouvait que renommer par-dessus, ce qui
        ajoutait une empreinte fausse à la banque au lieu d'en retirer une.
        Ici, la réunion oublie ; la banque se corrige avec `greffier connus`,
        qui montre déjà les entrées douteuses.
        """
        meeting = self.store.read(identifier)
        if voice not in meeting.names and voice not in meeting.propositions:
            raise KeyError(f"La voix « {voice} » ne porte aucun nom.")
        meeting.names.pop(voice, None)
        meeting.propositions.pop(voice, None)
        self.store.record(meeting)
        return meeting

    def accepter_propositions(self, identifier: str) -> dict[str, str]:
        """Valide d'un coup tous les noms devinés pendant la réunion.

        Pratique quand les propositions sont manifestement justes, mais c'est
        bien l'utilisateur qui décide : rien n'est validé sans ce geste.
        """
        meeting = self.store.read(identifier)
        acceptes = dict(meeting.propositions)
        for voice, name in acceptes.items():
            self.name_voice(identifier, voice, name)
        return acceptes
