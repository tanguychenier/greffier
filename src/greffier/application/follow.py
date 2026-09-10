"""Suivre la réunion pendant qu'elle a lieu, et se laisser corriger.

Deux processus, un fichier. Celui qui écoute transcrit, attribue et **ajoute** au
journal ; la fenêtre le lit au fil de l'eau et y dépose ses corrections. Aucun
démon, aucun port réseau : le même choix que pour l'état de l'enregistrement, et
pour la même raison — un fichier survit à tout, et se relit après un plantage.

Pourquoi deux processus plutôt qu'un fil dans la fenêtre : whisper occupe
plusieurs secondes de calcul par tranche, ce qui gèlerait l'interface, et un
modèle qui tombe ne doit pas emporter la fenêtre avec lui. C'est arrivé — voir
le rapport de plantage cité dans `fenetre`.

Le journal est **en ajout seul**, y compris pour les corrections : une
correction ne réécrit pas les lignes passées, elle en publie une qui dit ce
qu'elle change. La fenêtre applique la même règle à son propre exemplaire du
fil, ce qui la rend réactive au clic sans attendre la tranche suivante.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from greffier.domain.channels import subtract
from greffier.domain.live import (
    Block,
    Certainty,
    Correction,
    Join,
    LiveThread,
    LiveTurn,
    LiveVoice,
    blocks,
)
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.voiceprints import aggregate
from greffier.ports import outbound

TRANCHE_MINIMALE_S = 3.0

GENRE_TOUR = "tour"
GENRE_CORRECTION = "correction"
GENRE_ETAT = "etat"
GENRE_REUNION = "reunion"
GENRE_SEPARATION = "separation"

@dataclass(frozen=True, slots=True)
class Position:
    """Où en est l'enregistrement, d'après ce qui est réellement écrit.

    L'horloge de la réunion ne convient pas : elle retire les pauses, alors que
    le fichier, lui, ne contient que ce qui a été capté. Les deux divergent de
    tout le temps d'arrêt, et transcrire à la position de l'horloge relit un
    passage déjà vu — ou lit au-delà du fichier, donc rien.
    """

    morceau: Path
    ecrit: float
    decalage: float

    @property
    def overall(self) -> float:
        return self.decalage + self.ecrit

def position(
    chunks: list[Path], duration: Callable[[Path], float | None]
) -> Position | None:
    """La position dans le dernier morceau, et le temps déjà enregistré avant.

    Un enregistrement se coupe en plusieurs morceaux dès qu'on met en pause ou
    qu'on branche un casque. Le direct suit **le dernier**, et cumule les
    précédents pour que l'horodatage affiché reste celui de la réunion.
    """
    present_line = [m for m in chunks if duration(m) is not None]
    if not present_line:
        return None
    decalage = 0.0
    for morceau in present_line[:-1]:
        decalage += duration(morceau) or 0.0
    dernier = present_line[-1]
    return Position(morceau=dernier, ecrit=duration(dernier) or 0.0, decalage=decalage)

# ------------------------------------------------------------------ le journal

def files(folder: Path, identifier: str) -> tuple[Path, Path]:
    """Le journal du direct et le dépôt des corrections, pour une réunion.

    Deux fichiers plutôt qu'un : celui qui écoute écrit dans le premier et lit le
    second, la fenêtre fait l'inverse. Aucun des deux n'écrit là où l'autre écrit,
    donc aucun verrou à poser.
    """
    return (
        folder / f"{identifier}.jsonl",
        folder / f"{identifier}.corrections.jsonl",
    )

def _ligne_tour(turn: LiveTurn, voice: LiveVoice) -> dict[str, Any]:
    """Ce qu'une phrase publie d'elle-même.

    L'état de la voix voyage avec chaque phrase : la fenêtre peut alors se
    reconstruire depuis n'importe quel point du journal, sans supposer avoir vu
    les lignes précédentes.
    """
    return {
        "genre": GENRE_TOUR,
        "numero": turn.number,
        "debut": round(turn.span.start, 2),
        "fin": round(turn.span.end, 2),
        "texte": turn.text,
        "voix": turn.voice,
        "nom": voice.name,
        "certitude": voice.certitude.value,
        "rang": voice.rank,
    }

def _ligne_correction(correction: Correction) -> dict[str, Any]:
    return {
        "genre": GENRE_CORRECTION,
        "nom": correction.name,
        "voix": correction.voice,
        "numeros": list(correction.numeros),
        "toute_la_voix": correction.whole_voice,
    }

def _ligne_reunion(source: str, target: str) -> dict[str, Any]:
    return {"genre": GENRE_REUNION, "voix": source, "vers": target}

def _ligne_separation(fusion: Join) -> dict[str, Any]:
    """De quoi rendre la séparation à la fenêtre, et à un fil repris.

    La fenêtre ne calcule aucune empreinte : elle a besoin du **résultat**, donc
    des numéros de tours et de l'état rendu à la voix, pas de quoi le refaire.
    """
    return {
        "genre": GENRE_SEPARATION,
        "voix": fusion.source,
        "de": fusion.target,
        "numeros": list(fusion.numeros),
        "nom": fusion.name,
        "certitude": fusion.certitude.value,
        "rang": fusion.rank,
        "nom_cible": fusion.nom_cible,
        "certitude_cible": fusion.certitude_cible.value,
    }

def add(log: Path, lines: list[dict[str, Any]]) -> None:
    """Ajoute au journal, une ligne par événement.

    En ajout et non réécrit : la fenêtre peut le suivre sans jamais tomber sur
    un fichier à moitié écrit, et une interruption ne perd pas ce qui précède.
    """
    if not lines:
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as flux:
        for line in lines:
            flux.write(json.dumps(line, ensure_ascii=False) + "\n")

def read_from(log: Path, position_octets: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Les lignes ajoutées depuis la dernière lecture, et où reprendre.

    Une lecture incrémentale, parce que la fenêtre relit quatre fois par
    seconde : relire une heure de réunion à chaque fois coûterait pour rien.
    Une ligne incomplète — le fichier est en cours d'écriture — est laissée pour
    la fois suivante.
    """
    if not log.exists():
        return [], position_octets
    try:
        with log.open("rb") as flux:
            flux.seek(position_octets)
            brut = flux.read()
    except OSError:
        return [], position_octets
    if not brut:
        return [], position_octets
    complet = brut.rfind(b"\n")
    if complet < 0:
        return [], position_octets
    lines: list[dict[str, Any]] = []
    for text in brut[: complet + 1].decode("utf-8", errors="replace").splitlines():
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines, position_octets + complet + 1

def replay(lines: list[dict[str, Any]], thread: LiveThread | None = None) -> LiveThread:
    """Reconstruit le fil depuis le journal, pour l'afficher.

    La fenêtre travaille ainsi sur les mêmes objets que le processus qui écoute,
    donc avec les mêmes règles de correction — sans jamais charger un modèle.
    """
    thread = thread if thread is not None else LiveThread()
    for line in lines:
        kind = line.get("genre")
        if kind == GENRE_TOUR:
            _replay_turn(thread, line)
        elif kind == GENRE_CORRECTION:
            _replay_correction(thread, line)
        elif kind == GENRE_REUNION:
            _replay_join(thread, line)
        elif kind == GENRE_SEPARATION:
            _replay_split(thread, line)
    return thread

def _replay_split(thread: LiveThread, line: dict[str, Any]) -> None:
    """Rejoue une séparation : les tours nommés repassent à la voix rendue.

    Sans partage des empreintes, que la fenêtre n'a pas : elle n'a besoin que de
    savoir qui parle. Ce que le fil garde, c'est la paire tenue à part, pour
    qu'une reprise de fil ne refasse pas la fusion défaite.
    """
    rendue, target = str(line.get("voix", "")), str(line.get("de", ""))
    if not rendue or not target or rendue == target:
        return
    # Consignée d'abord, et sans condition : c'est le seul fait qui doit
    # survivre à tout, y compris à un journal dont on n'a lu que la fin. Sans
    # lui, la tranche suivante refait la fusion et le clic n'a servi à rien.
    thread.split_apart.add(frozenset({rendue, target}))
    gardee = thread.voice.get(target)
    if rendue in thread.voice or gardee is None:
        return
    numeros = {int(n) for n in line.get("numeros", [])}
    thread.reserve_identifier(rendue)
    thread.voice[rendue] = LiveVoice(
        identifier=rendue,
        name=line.get("nom"),
        certitude=_certitude(line.get("certitude")),
        rank=int(line.get("rang", 0)),
    )
    if gardee.certitude is not Certainty.HUMAINE:
        gardee.name = line.get("nom_cible")
        gardee.certitude = _certitude(line.get("certitude_cible"))
    for turn in thread.turns:
        if turn.voice == target and turn.number in numeros:
            turn.voice = rendue
    thread.split_apart.add(frozenset({rendue, target}))

def _certitude(value: Any) -> Certainty:
    try:
        return Certainty(str(value))
    except ValueError:
        return Certainty.INCONNUE

def _replay_join(thread: LiveThread, line: dict[str, Any]) -> None:
    """Rejoue une réunion de voix : les tours de la source passent à la cible.

    La fenêtre reconstruit le fil depuis le journal, sans jamais calculer
    d'empreinte : il lui faut donc le **résultat** du recollage, pas de quoi le
    refaire.
    """
    source, target = str(line.get("voix", "")), str(line.get("vers", ""))
    if not source or not target or source == target:
        return
    avalee, gardee = thread.voice.get(source), thread.voice.get(target)
    if avalee is None or gardee is None:
        # Journal tronqué, ou voix jamais vue de ce côté : on retague quand même,
        # pour que la phrase s'affiche sous la voix qui a survécu.
        for turn in thread.turns:
            if turn.voice == source:
                turn.voice = target
        thread.voice.pop(source, None)
        return
    ferme_avant = avalee.certitude.firm
    nom_avant, certitude_avant = avalee.name, avalee.certitude
    # Par `reunir` et non à la main : c'est ce qui garde de quoi séparer ensuite.
    thread.join_into(source, target)
    # Le nom le plus sûr des deux survit : une voix anonyme absorbée par une
    # voix nommée ne doit pas effacer ce nom, ni l'inverse.
    if not gardee.certitude.firm and ferme_avant:
        gardee.name, gardee.certitude = nom_avant, certitude_avant

def _replay_turn(thread: LiveThread, line: dict[str, Any]) -> None:
    identifier = str(line.get("voix", ""))
    if not identifier:
        return
    thread.reserve_identifier(identifier)
    voice = thread.voice.get(identifier)
    if voice is None:
        voice = LiveVoice(identifier=identifier)
        thread.voice[identifier] = voice
    # Une correction déjà appliquée ne se laisse pas défaire par une ligne plus
    # ancienne : c'est la règle du domaine, la fenêtre ne la contourne pas.
    if not voice.certitude.firm:
        voice.name = line.get("nom")
        voice.certitude = Certainty(line.get("certitude", Certainty.INCONNUE.value))
        voice.rank = int(line.get("rang", 0))
    number = int(line.get("numero", len(thread.turns) + 1))
    if any(t.number == number for t in thread.turns):
        return
    start, end = float(line.get("debut", 0.0)), float(line.get("fin", 0.0))
    thread.turns.append(LiveTurn(
        number=number,
        span=Span(start, max(start, end)),
        text=str(line.get("texte", "")),
        voice=identifier,
    ))
    thread.jusqu_a = max(thread.jusqu_a, end)

def _replay_correction(thread: LiveThread, line: dict[str, Any]) -> None:
    numeros = [int(n) for n in line.get("numeros", [])]
    name = str(line.get("nom", "")).strip()
    if not name or not numeros:
        return
    # La portée telle qu'elle a été décidée. Déduite du nombre de numéros
    # auparavant, ce qui rejouait en « seulement cette phrase » une correction
    # portant sur toute une voix qui n'avait alors qu'un tour : à la reprise du
    # fil, les tours suivants de cette voix perdaient le nom.
    whole_voice = bool(line.get("toute_la_voix", len(numeros) > 1))
    known = {t.number for t in thread.turns}
    for number in numeros:
        if number in known:
            thread.correct(number, name, whole_voice=whole_voice)
            return

# ----------------------------------------------------- les corrections humaines

def request_a_split(requests: Path, voice: str) -> None:
    """Dépose une séparation pour le processus qui écoute.

    Même canal que les corrections, et pour la même raison : c'est lui qui tient
    les empreintes, donc lui seul peut les rendre à chaque voix — et c'est de ça
    que dépend ce qui entrera en banque.
    """
    requests.parent.mkdir(parents=True, exist_ok=True)
    with requests.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps({"separer": voice}, ensure_ascii=False) + "\n")

def ask(requests: Path, number: int, name: str, whole_voice: bool = True) -> None:
    """Dépose une correction pour le processus qui écoute.

    La fenêtre l'applique déjà à son propre affichage : ce fichier sert à ce que
    les tranches suivantes en tiennent compte, et à ce que l'empreinte entre en
    banque de voix.
    """
    requests.parent.mkdir(parents=True, exist_ok=True)
    with requests.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(
            {"numero": number, "nom": name, "toute_la_voix": whole_voice},
            ensure_ascii=False,
        ) + "\n")

# ------------------------------------------------------------------- le suivi

@dataclass
class Follower:
    """Attribue et publie ce qui se dit, tranche après tranche.

    Ne transcrit pas lui-même : les répliques lui arrivent, parce que la veille
    des propositions les utilise aussi et qu'il serait absurde de transcrire deux
    fois la même tranche.
    """

    thread: LiveThread
    log: Path
    requests: Path
    channels: outbound.ChannelReader | None = None
    extractor: outbound.VoiceprintExtractor | None = None
    bank: outbound.VoiceBank | None = None
    identifier: str = ""
    _lues: int = field(default=0, repr=False)
    _appris: dict[str, str] = field(default_factory=dict, repr=False)

    def take_in(
        self, tranche: Path, utterances: list[Utterance], decalage: float
    ) -> list[LiveTurn]:
        """Attribue les phrases d'une tranche et les publie.

        `repliques` est daté dans la tranche ; `decalage` remet à l'heure de la
        réunion. Les deux repères sont nécessaires : l'empreinte se prélève dans
        la tranche, l'affichage se fait à l'heure de la réunion.
        """
        self.apply_requests()
        locaux = self.channels.local_passages(tranche) if self.channels else []
        globaux = [
            Span(x.start + decalage, x.end + decalage) for x in locaux
        ]
        recalees = [
            Utterance(
                span=Span(
                    r.span.start + decalage, r.span.end + decalage
                ),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in utterances
        ]
        kept = self.thread.retenir(recalees)
        if not kept:
            return []

        nouveaux: list[LiveTurn] = []
        lines: list[dict[str, Any]] = []
        for bloc in blocks(kept, globaux):
            voiceprint = self._voiceprint(tranche, bloc, locaux, decalage)
            voice = self.thread.attach(voiceprint, bloc.locale)
            for turn in self.thread.record_turn(bloc, voice):
                nouveaux.append(turn)
                lines.append(_ligne_tour(turn, self.thread.voice[voice]))
        # Le recollage, maintenant que la tranche a versé sa matière : c'est là
        # que deux voix nées d'empreintes courtes se révèlent être la même
        # personne. Sans cette seconde chance, chaque reprise de parole créait
        # une voix — mesuré, 0,69 de ressemblance phrase à phrase contre 0,79
        # sur les agrégats, pour un seuil à 0,75.
        for source, target in self.thread.stitch():
            lines.append(_ligne_reunion(source, target))
        add(self.log, lines)
        self.learn_named_voices()
        return nouveaux

    def _voiceprint(
        self, tranche: Path, bloc: Block, locaux: list[Span], decalage: float
    ) -> Voiceprint | None:
        """L'empreinte d'un passage distant, prélevée sur ce qui est vraiment distant.

        Rien n'est prélevé sur la voix locale : le micro l'a déjà identifiée, et
        dépenser du calcul pour confirmer ce qui est certain n'apporte rien.

        Les portions locales sont **ôtées** de l'extrait avant le prélèvement.
        La transcription coupe à la phrase, pas au changement de locuteur : sans
        ce nettoyage, 0,6 s de voix locale restée en tête d'un extrait de 1,5 s
        suffisait à faire de la même personne deux participants — mesuré, et
        c'est ce qui empêchait une correction de se propager.
        """
        if bloc.locale or self.extractor is None:
            return None
        within_the_slice = Span(
            max(0.0, bloc.span.start - decalage),
            max(0.0, bloc.span.end - decalage),
        )
        chunks = subtract(within_the_slice, locaux)
        if not chunks:
            return None
        try:
            trouvees = self.extractor.extract_spans(tranche, chunks)
        except (RuntimeError, OSError, ValueError):
            # Un extrait que le modèle refuse ne doit pas interrompre la
            # réunion : la phrase s'affiche sans nom, et se corrige d'un clic.
            return None
        if not trouvees:
            return None
        return trouvees[0] if len(trouvees) == 1 else aggregate(trouvees)

    # ------------------------------------------------------------ corrections

    def apply_requests(self) -> list[Correction]:
        """Prend en compte ce que la fenêtre a corrigé depuis la dernière fois.

        Deux conséquences, et la seconde est celle qui compte : les tranches
        suivantes portent le bon nom, et l'empreinte entre en **banque de voix**.
        C'est ce qui fait que le compte rendu final retrouve la personne tout
        seul, sans qu'on ait à recorriger après la réunion.
        """
        lines, self._lues = read_from(self.requests, self._lues)
        faites: list[Correction] = []
        confirmations: list[dict[str, Any]] = []
        for line in lines:
            if "separer" in line:
                defaite = self.thread.split(str(line["separer"]))
                if defaite is not None:
                    confirmations.append(_ligne_separation(defaite))
                continue
            correction = self._appliquer(line)
            if correction is None:
                continue
            faites.append(correction)
            confirmations.append(_ligne_correction(correction))
        add(self.log, confirmations)
        self.learn_named_voices()
        return faites

    def _appliquer(self, line: dict[str, Any]) -> Correction | None:
        try:
            return self.thread.correct(
                number=int(line["numero"]),
                name=str(line["nom"]),
                whole_voice=bool(line.get("toute_la_voix", True)),
            )
        except (KeyError, ValueError, TypeError):
            # Une demande qui ne correspond à rien — journal effacé, numéro
            # inconnu — est ignorée : la réunion continue.
            return None

    def learn_named_voices(self) -> list[str]:
        """Verse en banque les voix qu'un humain a nommées, dès qu'elles ont de quoi.

        Une correction se saisit dès la première phrase — c'est bien le but —
        alors que l'empreinte n'a pas encore la matière du seuil. Refuser une
        fois pour toutes revenait à perdre la correction : elle s'affichait,
        puis ne servait ni à la réunion suivante, ni au compte rendu. On repasse
        donc à chaque tranche, jusqu'à ce qu'il y ait de quoi apprendre.
        """
        if self.bank is None:
            return []
        appris: list[str] = []
        for voice in self.thread.voice.values():
            if voice.certitude is not Certainty.HUMAINE or voice.name is None:
                continue
            if self._appris.get(voice.identifier) == voice.name:
                continue
            voiceprint = self.thread.voiceprint_to_learn(voice)
            if voiceprint is None:
                continue
            with contextlib.suppress(OSError):
                self.bank.record(
                    voice.name, replace(voiceprint, origine=self.identifier))
                self._appris[voice.identifier] = voice.name
                appris.append(voice.name)
        return appris

    def annoncer(self, message: str, active: bool = True) -> None:
        """Dit à la fenêtre ce que le direct peut faire, ou pourquoi il ne peut pas.

        Sans cela, un modèle absent se traduisait par un onglet vide, qui se lit
        comme « personne ne parle » plutôt que comme « rien n'écoute ».
        """
        add(self.log, [{"genre": GENRE_ETAT, "message": message, "actif": active}])

def known_people(bank: outbound.VoiceBank | None) -> list[Person]:
    """La banque de voix, ou rien si elle n'est pas lisible.

    Le direct doit démarrer même sans banque : c'est le cas de la première
    réunion, où personne n'est encore connu.
    """
    if bank is None:
        return []
    try:
        return bank.people()
    except OSError:
        return []
