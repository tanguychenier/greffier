"""Veiller pendant la réunion, sans jamais agir seul.

Deux boucles de rythmes différents, parce que les deux sources n'ont pas le même
coût : le presse-papier se relit en quelques millisecondes, la transcription
d'une tranche demande plusieurs secondes de calcul.

Rien n'est exécuté. Les propositions s'accumulent dans un fichier que
l'interface lit et présente ; c'est un humain qui déclenche. Une action lancée
seule sur une phrase mal transcrite, au milieu d'une réunion confidentielle, se
retourne vite contre son auteur.
"""

from __future__ import annotations

import contextlib
import json
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from greffier.application.follow import TRANCHE_MINIMALE_S, Follower, Position
from greffier.application.take_part import AssistantSettings
from greffier.domain.instructions import Proposition, WatchRules
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Opening
from greffier.ports import outbound

SYSTEM = platform.system()

ATTENDENT_UNE_REPONSE = frozenset({
    Because.VOIX_INDISTINCTE,
    Because.DECISION_SANS_SUITE,
    Because.QUESTION_SANS_REPONSE,
    Because.ECART_AVEC_UN_DOCUMENT,
    Because.CONTRIBUTION,
})

# Le presse-papier est gratuit à relire : on le fait souvent, pour que le lien
# collé apparaisse pendant qu'on en parle encore.
PERIODE_PRESSE_PAPIER = 2.0
# Une tranche de transcription coûte plusieurs secondes de calcul. Trop souvent,
# on prend du temps machine à la réunion elle-même.
SLICE_PERIOD = 30.0
# Recouvrement entre deux tranches : une phrase à cheval doit rester entière
# dans au moins l'une des deux.
OVERLAP = 5.0
# Une tranche ratée est reprise à la suivante, avec un peu plus de matière. Sans
# borne, un échec durable — modèle absent, fichier illisible — la ferait grandir
# jusqu'à demander plusieurs minutes de calcul à chaque tour.
TRANCHE_MAXIMALE = 90.0
# Secondes d'audio **déjà transcrit** données en plus au modèle, avant la
# tranche. Rien n'en est réaffiché : c'est du contexte, et il change tout.
#
# Mesuré le 2026-09-09 sur une réunion en présentiel, même passage, même modèle,
# seule la longueur de la fenêtre changeant : à 15 s « sur la ZIS », à 30 s
# « sur Asis », à 60 s « sur Oasis » — le mot juste, et la phrase entière avec.
# Whisper décode par fenêtres de 30 s en reportant le texte de la précédente en
# contexte : ne lui donner que la tranche, c'est le priver de ce sur quoi il
# s'appuie, et il comble avec ce qui ressemble.
#
# Le coût tient dans le budget : 0,9 s pour 15 s d'audio, 1,4 s pour 60 s avec
# huit fils, pour une tranche qui en dure dix.
CONTEXTE_S = 50.0

def _within_the_slice(utterances: list[Utterance], frontiere: float) -> list[Utterance]:
    """Ne garde que ce qui déborde dans la tranche, remis à l'heure de celle-ci.

    Une réplique entièrement dans le contexte a déjà été affichée : la
    réafficher doublerait chaque phrase. Une réplique à cheval est gardée
    entière — le texte déjà montré en sera retiré à l'affichage, ce qui vaut
    mieux que de couper une phrase au milieu.
    """
    if frontiere <= 0:
        return utterances
    kept = []
    for utterance in utterances:
        if utterance.span.end <= frontiere:
            continue
        kept.append(Utterance(
            span=Span(
                max(0.0, utterance.span.start - frontiere),
                utterance.span.end - frontiere,
            ),
            text=utterance.text, voice=utterance.voice, source=utterance.source,
        ))
    return kept

def read_the_clipboard() -> str:
    """Contenu du presse-papier, ou vide si le système ne le donne pas."""
    commands = {
        "Darwin": ["pbpaste"],
        "Linux": (["wl-paste"] if _exists("wl-paste")
                  else ["xclip", "-o", "-selection", "clipboard"]),
        "Windows": ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
    }
    command = commands.get(SYSTEM)
    if not command:
        return ""
    try:
        return subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""

def _exists(programme: str) -> bool:
    import shutil

    return shutil.which(programme) is not None

def extract_slice(audio: Path, start: float, end: float, destination: Path) -> Path | None:
    """Découpe un morceau d'un enregistrement **en cours d'écriture**.

    ffmpeg lit sans gêner l'écriture : c'est ce qui permet de transcrire une
    réunion pendant qu'elle a lieu, sans toucher au fichier qui s'écrit.
    """
    if not audio.exists() or audio.stat().st_size < 1024:
        return None
    outcome = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
         "-i", str(audio), "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, check=False,
    )
    if outcome.returncode != 0 or not destination.exists():
        return None
    return destination if destination.stat().st_size > 1024 else None

@dataclass
class Watcher:
    """Fait tourner la veille tant que la réunion est enregistrée."""

    watch_rules: WatchRules
    log: Path
    transcriber: outbound.Transcriber | None = None
    situer: Callable[[], Position | None] | None = None
    follower: Follower | None = None
    preparateur: outbound.AudioRecorder | None = None
    language: str = "fr"
    interrogate: Callable[[str], None] | None = None
    prompt_seed: str = ""
    relire_l_amorce: Callable[[], str] | None = None
    assistant_of: AssistantSettings | None = None
    reread_participation: Callable[[], tuple[bool, bool]] | None = None
    give_voice_back: Callable[[], Any] | None = None
    initiative: bool = False
    material_before_asking: float = 30.0
    slice_period: float = SLICE_PERIOD
    traite: float = 0.0
    vu: float | None = None

    def _current_prompt_seed(self) -> str:
        """L'amorce à donner à cette tranche, contexte relu s'il a changé.

        Relire un fichier toutes les dix secondes ne coûte rien mesurable, et
        c'est le prix pour qu'« ajoute OTP au contexte » serve à la phrase
        suivante et non à la réunion d'après. C'est en réunion qu'on découvre
        les mots qui manquent, donc c'est là que l'apprentissage doit porter.
        """
        if self.relire_l_amorce is None:
            return self.prompt_seed
        try:
            fraiche = self.relire_l_amorce()
        except OSError:
            return self.prompt_seed
        if fraiche and fraiche != self.prompt_seed:
            self.prompt_seed = fraiche
        return self.prompt_seed

    def publish(self, nouvelles: list[Proposition]) -> None:
        """Ajoute au journal, une proposition par ligne.

        Un fichier en ajout plutôt qu'un fichier réécrit : l'interface peut le
        suivre au fil de l'eau, et une interruption ne perd rien de ce qui
        précède.
        """
        if not nouvelles:
            return
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as flux:
            for proposition in nouvelles:
                flux.write(json.dumps({
                    "genre": proposition.kind.value,
                    "texte": proposition.text,
                    "instant": round(proposition.at_instant, 1),
                    "origine": proposition.origine.value,
                    "contexte": proposition.context,
                }, ensure_ascii=False) + "\n")

    def clipboard_turn(self, at_instant: float) -> list[Proposition]:
        content = read_the_clipboard()
        nouvelles = self.watch_rules.paste(content, at_instant) if content else []
        self.publish(nouvelles)
        return nouvelles

    def transcription_turn(self, ou: Position, job: Path) -> list[Proposition]:
        """Transcrit ce qui a été enregistré depuis la dernière tranche.

        Le découpage se fait sur ce que le fichier **porte réellement**, jamais
        sur l'horloge : après une pause, les deux ont divergé de tout le temps
        d'arrêt, et lire à la position de l'horloge demandait à ffmpeg un passage
        au-delà de la fin du fichier — donc rien.
        """
        if self.transcriber is None:
            return []
        start = max(0.0, self.traite - ou.decalage - OVERLAP, ou.ecrit - TRANCHE_MAXIMALE)
        if ou.ecrit - start < TRANCHE_MINIMALE_S:
            return []
        tranche = extract_slice(ou.morceau, start, ou.ecrit, job / "tranche.wav")
        if tranche is None:
            return []
        # Le modèle reçoit la tranche **précédée** de ce qui a déjà été
        # transcrit ; seules les répliques qui débordent dans la tranche sont
        # gardées. Le reste n'est là que pour qu'il sache de quoi on parle.
        depart = max(0.0, start - CONTEXTE_S)
        avec_contexte = tranche if depart >= start else (
            extract_slice(ou.morceau, depart, ou.ecrit, job / "fenetre.wav")
            or tranche
        )
        # Deux versions de la même tranche, et c'est nécessaire : la
        # transcription veut un mélange équilibré, l'attribution veut les
        # niveaux **relatifs** intacts, puisque c'est l'écart entre le micro et
        # la boucle qui dit qui parle. Normaliser avant d'attribuer ferait
        # passer tout le monde pour la personne qui enregistre.
        a_transcrire = avec_contexte
        if self.preparateur is not None:
            a_transcrire = self.preparateur.prepare_transcript(
                avec_contexte, job / "tranche-niveau.wav"
            )
        try:
            utterances = self.transcriber.transcribe(
                a_transcrire, self.language, self._current_prompt_seed()
            )
        except (RuntimeError, OSError):
            # Une tranche ratée ne doit pas interrompre la veille : la réunion
            # continue, et la transcription définitive se fera à la fin.
            return []
        utterances = _within_the_slice(utterances, start - depart)
        self.traite = ou.decalage + ou.ecrit
        # Pendant la réunion, sur ce qui vient d'être dit : après coup, une
        # question sur un terme mal entendu arrive trop tard pour que le compte
        # rendu en profite.
        if self.interrogate is not None:
            for utterance in utterances:
                with contextlib.suppress(OSError):
                    self.interrogate(utterance.text)
        decalage = ou.decalage + start
        # Les répliques sont datées dans la tranche : on les remet à l'heure de
        # la réunion, sinon les propositions renverraient au mauvais moment.
        recalees = [
            Utterance(
                span=Span(
                    r.span.start + decalage, r.span.end + decalage
                ),
                text=r.text, voice=r.voice, source=r.source,
            )
            for r in utterances
        ]
        nouvelles = self.watch_rules.listen(recalees)
        self.publish(nouvelles)
        if self.follower is not None:
            # Le fil affiché reçoit la tranche elle-même : l'empreinte vocale se
            # prélève dedans, aux temps de la tranche.
            self.follower.take_in(tranche, utterances, decalage)
        self.assistant_turn(recalees, self.traite)
        return nouvelles

    def assistant_turn(self, utterances: list[Utterance], now: float) -> None:
        """Laisse l'assistant décider s'il a quelque chose à dire, et le dire.

        Après l'affichage, jamais avant : ce qui se dit doit être visible même
        quand l'assistant se tait, ce qui est le cas la plupart du temps.
        """
        if self.assistant_of is None:
            return
        if self.reread_participation is not None:
            with contextlib.suppress(OSError):
                self._apply_the_buttons(*self.reread_participation())
        retenue = self.assistant_of.turn(
            utterances, now,
            turns=self._turn_bounds(),
            occasions=self._voices_to_ask_about(now),
        )
        if retenue is None:
            if self.initiative:
                # Rien à dire maintenant : on cherche s'il y aura quelque chose
                # à dire tout à l'heure. La recherche coûte un appel au modèle,
                # donc elle se fait à côté et son résultat sert à la tranche
                # suivante.
                self.assistant_of.look_for_a_contribution_aside(now)
            return
        if retenue.because in ATTENDENT_UNE_REPONSE:
            # On retient la question posée : c'est ce qui permet à la réponse
            # d'être comprise comme une réponse, et pas comme une phrase de plus.
            # Répondre à quelqu'un n'attend rien en retour ; poser une question
            # de soi-même, si.
            self.assistant_of.awaiting = retenue
        self.assistant_of.answer_aside(retenue, now)

    def _apply_the_buttons(self, a_voix_haute: bool, de_lui_meme: bool) -> None:
        """Suit les deux boutons de la fenêtre, sans redémarrer quoi que ce soit.

        Se taire est immédiat, phrase en cours comprise : appuyer sur le bouton
        pendant qu'il parle doit l'interrompre, pas attendre la fin de sa
        tirade. Reprendre la parole ne coûte le chargement du modèle qu'une
        fois, et seulement si on la lui redonne.

        L'initiative se relit ici et non au démarrage : sans cela, le bouton
        n'agissait qu'à la réunion suivante, ce qui ne se devine pas.
        """
        if self.assistant_of is None:
            return
        lui = self.assistant_of
        self.initiative = de_lui_meme
        if not a_voix_haute and lui.voice is not None:
            lui.voice.go_quiet()
            lui.voice = None
        elif a_voix_haute and lui.voice is None and self.give_voice_back is not None:
            lui.voice = self.give_voice_back()

    def _turn_bounds(self) -> list[tuple[float, float]]:
        """Les tours de parole affichés, pour mesurer la densité de la discussion."""
        if self.follower is None:
            return []
        return [(t.span.start, t.span.end) for t in self.follower.thread.turns]

    def _voices_to_ask_about(self, now: float) -> list[Opening]:
        """Une voix qui a parlé longtemps sans qu'on sache de qui elle est.

        C'est le défaut le plus coûteux de l'outil : elle deviendra
        « Personne 12 » dans le compte rendu, et plus personne ne saura la
        reconnaître. La demander sur le moment coûte une phrase et vaut un nom.
        """
        if self.follower is None or self.assistant_of is None or not self.initiative:
            return []
        for voice in self.follower.thread.voice.values():
            if (voice.name is None and voice.nameable
                    and voice.seconds >= self.material_before_asking):
                return [self.assistant_of.ask_who_is_speaking(voice.identifier, now)]
        return []

    def loop(
        self,
        still_running: Callable[[], bool],
        depuis: Callable[[], float],
        job: Path,
        pause: Callable[[float], None] = time.sleep,
    ) -> list[Proposition]:
        """Tourne jusqu'à la fin de l'enregistrement.

        Les deux rythmes sont gérés dans une seule boucle : deux fils
        d'exécution pour ça compliqueraient l'arrêt sans rien apporter.

        `depuis` donne l'heure de la réunion, pour horodater les liens collés.
        Le rythme des tranches, lui, suit l'audio écrit : en pause, rien ne
        s'ajoute au fichier, donc rien n'est transcrit — et la reprise repart où
        la capture s'était arrêtée.
        """
        while still_running():
            self.clipboard_turn(depuis())
            ou = self.situer() if self.situer is not None else None
            if ou is not None and self._is_time(ou):
                self.transcription_turn(ou, job)
            pause(PERIODE_PRESSE_PAPIER)
        self.last_pass(job)
        return self.watch_rules.propositions

    def last_pass(self, job: Path) -> list[Proposition]:
        """Transcrit ce qui restait quand la réunion s'est arrêtée.

        Il reste toujours jusqu'à une période d'audio non lue : sans cette
        passe, on finit sa phrase devant un fil qui s'arrête avant elle. Le
        fichier visé est alors celui que l'arrêt vient de recoller, où les temps
        sont déjà ceux de la réunion.
        """
        ou = self.situer() if self.situer is not None else None
        if ou is None or ou.overall - self.traite < TRANCHE_MINIMALE_S:
            return []
        return self.transcription_turn(ou, job)

    def _is_time(self, ou: Position) -> bool:
        """Faut-il transcrire maintenant ?

        Deux cas. Le rythme ordinaire : assez d'audio s'est ajouté. Et le
        rattrapage, quand le fichier **ne grandit plus** — mise en pause, ou fin
        de la réunion : sans lui, les dernières secondes de chaque prise de
        parole ne s'affichaient jamais, et l'on finissait sa phrase devant un fil
        qui s'arrêtait avant elle.
        """
        avance = ou.overall - self.traite
        stagne = self.vu is not None and abs(ou.ecrit - self.vu) < 0.05
        self.vu = ou.ecrit
        if avance >= self.slice_period:
            return True
        return stagne and avance >= TRANCHE_MINIMALE_S
