"""Making the assistant a participant rather than a passive mic.

The hard half is the silence: what it refuses to say is what makes it bearable
in a room. The manners live in the domain; here is the wiring — the brain, the
voice, the context.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from greffier.domain.models import Utterance
from greffier.domain.participation import (
    MEMORY_OF_ITS_WORDS,
    WORDS_TO_JUDGE,
    Because,
    Manners,
    Opening,
    called_by_name,
    is_own,
    own_words,
    question_asked,
    speech_density,
    without_own_name,
)

CONSIGNES_ORALES = """Tu t'appelles {name} et tu participes à une réunion de
travail. On t'entend par un haut-parleur : ce que tu écris sera prononcé tel
quel, à voix haute, devant les participants.

Réponds en **une à deux phrases**. Jamais de liste, de titre, de tableau, de
Markdown, d'URL ni de parenthèse : rien de tout cela ne s'entend. Pas de
préambule, pas de « bien sûr », pas de formule d'attente.

Tu parles à des gens qui sont en train de travailler. Si on ne te posait pas
vraiment de question — ton nom est passé dans une phrase qui ne t'était pas
adressée, ou l'échange se poursuit entre eux — réponds le mot {rien}, seul, et
rien d'autre. Tu te tairas. Dire « ce n'était pas une question pour moi » est
une intervention de plus : on l'entend, elle coupe la réunion, et elle apprend
à la salle que tu écoutes pour juger.

Deux sources, dans cet ordre. **Ce qui a été dit** fait autorité sur cette
réunion. Et **tu peux chercher en ligne** quand la question porte sur un fait
extérieur : une définition, une version, une norme, l'état d'un service, une
documentation. Cherche de ton propre chef quand cela répond mieux, sans
attendre qu'on te le demande, et sans annoncer que tu vas chercher.

Quand tu as cherché, **nomme la source à voix haute** — « d'après la
documentation de Symfony », « d'après le site de l'éditeur » — et jamais son
adresse : une URL ne s'entend pas. Si tu n'as trouvé nulle part, dis-le en une
phrase plutôt que de meubler.

N'emploie ni tiret cadratin ni demi-cadratin.
"""

CONTEXTE_MAXIMAL = 6000

NOTHING = "RIEN"

CONSIGNES_SUITE = """Tu t'appelles {name} et tu participes à une réunion. Tu as
posé une question, on vient de te répondre.

Si la réponse règle la question, dis-le en **une phrase courte** qui montre ce
que tu en as retenu, et rends la parole. Une phrase du genre « très bien, donc
c'est {exemple} qui s'en occupe » vaut mieux qu'un « merci » seul : elle prouve
que tu as compris, et elle laisse une trace juste dans le compte rendu.

Si la réponse ne règle rien et qu'une précision changerait le compte rendu,
demande-la, toujours en une phrase.

Sinon, réponds le mot {rien}, seul. C'est le cas si on t'a répondu à côté, si
la conversation est déjà repartie ailleurs, ou si tu n'aurais rien à ajouter
qu'une politesse : deux répliques de plus feraient de toi un participant de
trop.

Pas de liste, pas de titre, pas d'adresse web : ce sera prononcé tel quel.
N'emploie ni tiret cadratin ni demi-cadratin.

Ta question était : « {question} »
Ce qu'on vient de te répondre :
"""

CONSIGNES_APPORT = """Tu t'appelles {name} et tu assistes à une réunion de travail
sans y avoir été invitée à parler. On te donne ce qui vient de se dire.

Ta réponse par défaut est le mot {rien}, seul, sans rien d'autre. C'est la
réponse juste dans la très grande majorité des cas : une réunion se tient très
bien sans commentaire, et une remarque de trop coûte plus cher que dix
remarques manquées.

Tu ne sors de ce silence que si l'une de ces trois choses est vraie, et
manifestement vraie :

- une décision a été prise sans que personne ne soit désigné pour la porter,
  ou sans échéance alors qu'elle en appelle une ;
- une question a été posée à la cantonade et la conversation est passée à
  autre chose sans y répondre ;
- ce qui vient d'être dit contredit un document qu'on t'a fourni, ou une
  décision prise plus tôt dans cette même réunion.

Tu ne dis rien pour : reformuler ce qui vient d'être dit, résumer, approuver,
signaler qu'un sujet est intéressant, proposer une méthode qu'on ne t'a pas
demandée, ou rappeler une bonne pratique générale.

Si tu parles, c'est **une phrase**, à l'oral, sans liste ni titre ni adresse
web : elle sera prononcée telle quelle dans la pièce. Pose la question, ne
fais pas la leçon. N'emploie ni tiret cadratin ni demi-cadratin.

Ce qui vient de se dire :
"""

class Speaker(Protocol):
    """Whatever pronounces. NeuralVoice and SystemVoice both fit."""

    def say(self, text: str) -> bool:
        ...

    def go_quiet(self) -> None:
        ...

    def is_speaking(self) -> bool:
        ...

@dataclass(frozen=True, slots=True)
class Remark:
    """What the assistant said, and why."""

    remark: str
    because: Because
    a: float
    prononce: bool = False

@dataclass
class AssistantSettings:
    """Listens to the meeting, and speaks in it when that is worth doing."""

    name: str = "Greffier"
    manners: Manners = field(default_factory=Manners)
    voice: Speaker | None = None
    cerveau: Any | None = None
    context: Callable[[], str] | None = None
    setting: Callable[[], str] | None = None
    tracer: Callable[[str, str], None] | None = None
    awaiting: Opening | None = None
    name_voice: Callable[[str, str], bool] | None = None
    in_reserve: Opening | None = None
    its_own_turns: list[tuple[float, float]] = field(default_factory=list)
    keep_its_turn: Callable[[float, float], None] | None = None
    its_own_words: list[tuple[float, frozenset[str]]] = field(default_factory=list)
    stopped: bool = False
    _job: threading.Thread | None = None
    _search: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        """True while it is phrasing or speaking: nothing more to hand it."""
        return self._job is not None and self._job.is_alive()

    def stop(self) -> None:
        """Ends it for good: nothing more comes out of its mouth.

        It formulates in a separate thread and takes seconds to do it, so a
        remark decided just before the meeting ended would otherwise be
        pronounced after it.
        """
        self.stopped = True
        if self.voice is not None:
            with contextlib.suppress(Exception):
                self.voice.go_quiet()

    def turn(
        self,
        utterances: list[Utterance],
        now: float,
        turns: list[tuple[float, float]] | None = None,
        occasions: list[Opening] | None = None,
    ) -> Opening | None:
        """What the assistant takes from this slice, or nothing."""
        proposees = list(occasions or [])
        for utterance in utterances:
            text = utterance.text.strip()
            if not text or self._is_his_own(utterance, now):
                continue
            if self.awaiting is not None:
                accuse = self._acknowledge(text, utterance.span.end)
                if accuse is not None:
                    return accuse
            if called_by_name(text, self.name):
                demande = question_asked(text, self.name) or text
                proposees.append(Opening(
                    because=Because.APPELE,
                    remark=demande,
                    born_at=utterance.span.end,
                    # A subject, so a question the overlap brings back in the
                    # next slice is not answered a second time.
                    subject=f"appel:{_empreinte_du_propos(demande)}",
                ))
        if self.in_reserve is not None:
            proposees.append(self.in_reserve)
        lull = self._lull(utterances, now)
        density = speech_density(turns or [], now) if turns else 0.0
        retenue = self.manners.choose(proposees, now, lull, density)
        if retenue is not None and retenue is self.in_reserve:
            self.in_reserve = None
        return retenue

    def look_for_a_contribution_aside(self, now: float) -> None:
        """Looks, in a separate thread, for whether there is anything to say.

        The search costs a call to the model, so it happens aside and its result serves
        the following slice.
        """
        if self.in_reserve is not None or not self.manners.active:
            return
        if self._search is not None and self._search.is_alive():
            return

        def chercher() -> None:
            self.in_reserve = self.contribution(now)

        self._search = threading.Thread(target=chercher, daemon=True)
        self._search.start()

    def _is_his_own(self, utterance: Utterance, now: float = 0.0) -> bool:
        """Is this utterance the assistant hearing itself?

        By the **words** first. It speaks through the loudspeakers, the tool
        records the system output on purpose, so its own voice comes back on
        the channel meant for everybody else — and it then reads its own name
        in its own answer and answers again, for ever. Judged on the words
        because it answers late and in a separate thread: no window of time can
        be trusted.

        The time window is kept as a second net, for a remark whose
        transcription came back too mangled to recognise.
        """
        self._oublier_ses_vieux_mots(now or utterance.span.end)
        if is_own(utterance.text, [words for _when, words in self.its_own_words]):
            return True
        if len(own_words(utterance.text)) >= WORDS_TO_JUDGE:
            # Enough words to decide, so the time window has no business
            # here: it is estimated from the length of the text, and it
            # swallowed the next question, leaving the room unheard.
            return False
        start, end = utterance.span.start, utterance.span.end
        if end <= start:
            return False
        return any(
            min(end, sa_fin) - max(start, son_debut) > 0.5 * (end - start)
            for son_debut, sa_fin in self.its_own_turns
        )

    def _oublier_ses_vieux_mots(self, now: float) -> None:
        """Drops what it said long enough ago to belong to the room again."""
        self.its_own_words = [
            (when, words) for when, words in self.its_own_words
            if now - when <= MEMORY_OF_ITS_WORDS
        ]

    def _lull(self, utterances: list[Utterance], now: float) -> float:
        """How long since anyone last spoke."""
        if not utterances:
            return now
        return max(0.0, now - max(r.span.end for r in utterances))

    def _acknowledge(self, text: str, a: float) -> Opening | None:
        """Handles the sentence that answers the question asked."""
        attendue, self.awaiting = self.awaiting, None
        if attendue is None:
            return None
        if attendue.because is Because.INDISTINCT_VOICE:
            return self._name_from_answer(attendue, text, a)
        return self._follow_up_its_question(attendue, text, a)

    def _name_from_answer(
        self, attendue: Opening, text: str, a: float
    ) -> Opening | None:
        """"It's Hubert" becomes a name carried into the minutes.

        That is what separates an exchange from a question thrown into the air.
        """
        first_name = _first_name_in(text)
        voice = attendue.subject.removeprefix("voix:")
        if first_name and self.name_voice is not None and self.name_voice(voice, first_name):
            return Opening(
                because=Because.APPELE,
                remark=f"Merci, c'est noté : je mets {first_name} sur cette voix.",
                born_at=a,
                subject=f"merci:{voice}",
                as_is=True,
            )
        return None

    def _follow_up_its_question(
        self, attendue: Opening, text: str, a: float
    ) -> Opening | None:
        """Reacts to the answer just given, or keeps quiet."""
        if self.cerveau is None:
            return None
        guidance = CONSIGNES_SUITE.format(
            name=self.name, rien=NOTHING, question=attendue.remark, exemple="Hubert")
        try:
            remark = self._interrogate(guidance, text)
        except (RuntimeError, OSError):
            return None
        if not remark or remark.strip().upper().startswith(NOTHING):
            return None
        suite = Opening(
            because=Because.APPELE,
            remark=remark,
            born_at=a,
            subject=f"suite:{attendue.subject or _empreinte_du_propos(attendue.remark)}",
            as_is=True,
        )
        if remark.rstrip().endswith("?"):
            self.awaiting = suite
        return suite

    def answer(self, opening: Opening, now: float) -> Remark:
        """Phrases it, then says it. Blocking: see answer_aside.

        Its own name is taken out of whatever it is about to say, and that is a
        hard guarantee: what it says comes back through the capture loop, and a
        remark carrying its own name calls it again.
        """
        if self.stopped:
            return Remark(remark="", because=opening.because, a=now)
        remark = without_own_name(self._phrase_it(opening), self.name)
        if not remark or self.stopped:
            return Remark(remark="", because=opening.because, a=now)
        # Kept before speaking: a slice can come back while `say` still holds.
        self.its_own_words.append((now, own_words(remark)))
        prononce = bool(self.voice and self.voice.say(remark))
        if prononce:
            fin = now + 1.0 + len(remark) / 15.0
            self.its_own_turns.append((now, fin))
            if self.keep_its_turn is not None:
                with contextlib.suppress(Exception):
                    self.keep_its_turn(now, fin)
        self.manners.has_spoken(opening, now)
        if self.tracer is not None:
            with contextlib.suppress(OSError):
                self.tracer(self.name.lower(), remark)
        return Remark(remark=remark, because=opening.because, a=now,
                            prononce=prononce)

    def answer_aside(self, opening: Opening, now: float) -> None:
        """Answers in a separate thread, so as not to hold up transcription."""
        if self._job is not None and self._job.is_alive():
            return
        self._job = threading.Thread(
            target=self.answer, args=(opening, now), daemon=True)
        self._job.start()

    def _phrase_it(self, opening: Opening) -> str:
        """The exact remark to pronounce.

        Called by name with no brain to answer with, it says **nothing**. It
        used to return the remark it had been handed, which for a question is
        the question itself: it repeated what it had just been asked, its own
        name included, then heard itself and answered again. Fifteen times in
        fifteen seconds, in a real meeting. Echoing is worse than silence.
        """
        if opening.as_is or opening.because is not Because.APPELE:
            return opening.remark
        if self.cerveau is None:
            return ""
        material = ""
        if self.context is not None:
            with contextlib.suppress(OSError):
                material = str(self.context())[-CONTEXTE_MAXIMAL:]
        demande = (
            f"Voici ce qui s'est dit jusqu'ici dans la réunion :\n\n{material}\n\n"
            f"On vient de te dire : « {opening.remark} »\n\nRéponds."
        )
        try:
            remark = str(self.cerveau.write_up(demande)).strip()
        except (RuntimeError, OSError):
            return ""
        # Nothing to answer is an answer, and it is silence. Read back from a
        # real meeting: "Là c'était un échange entre vous, pas une question
        # pour moi, je vous laisse continuer", said out loud nine times.
        if remark.upper().startswith(NOTHING):
            return ""
        return remark

    def contribution(self, now: float) -> Opening | None:
        """What the assistant would have to add of its own, or nothing."""
        if self.cerveau is None or self.context is None:
            return None
        if self.manners.spoke_at is not None and (
                now - self.manners.spoke_at < self.manners.rest):
            return None
        try:
            material = str(self.context())[-CONTEXTE_MAXIMAL:]
        except OSError:
            return None
        if not material.strip():
            return None
        guidance = CONSIGNES_APPORT.format(name=self.name, rien=NOTHING)
        try:
            remark = self._interrogate(guidance, material)
        except (RuntimeError, OSError):
            return None
        if not remark or remark.strip().upper().startswith(NOTHING):
            return None
        return Opening(
            because=Because.CONTRIBUTION,
            remark=remark,
            born_at=now,
            subject=f"apport:{_empreinte_du_propos(remark)}",
        )

    def _interrogate(self, guidance: str, material: str) -> str:
        """A call to the brain, with guidance that is not the writer's."""
        cerveau = self.cerveau
        if cerveau is None:
            return ""
        avant = getattr(cerveau, "consignes_propres", None)
        try:
            if avant is not None:
                cerveau.consignes_propres = guidance
                return str(cerveau.write_up(material)).strip()
            return str(cerveau.write_up(guidance + material)).strip()
        finally:
            if avant is not None:
                cerveau.consignes_propres = avant

    def ask_who_is_speaking(self, voice: str, now: float) -> Opening:
        """The question that settles the tool's most expensive problem.

        An unnamed voice becomes "Personne 12" in the minutes and nobody can recognise
        it afterwards. Asking on the spot costs one sentence and earns a name.
        """
        return Opening(
            because=Because.INDISTINCT_VOICE,
            remark="Excusez-moi, je n'arrive pas à situer la voix qui vient de "
                   "parler. Est-ce que cette personne peut dire son prénom ?",
            born_at=now,
            subject=f"voix:{voice}",
            as_is=True,
        )

    def guidance(self) -> str:
        """What the assistant is told once, before the meeting starts.

        The setting comes with it: the acronyms of this organisation and the
        people in it. Without them it answers on the words it hears, and this
        room says "CASA" and "visa" for things no general model knows.
        """
        consignes = CONSIGNES_ORALES.format(name=self.name, rien=NOTHING)
        milieu = self._le_milieu()
        return f"{milieu}{consignes}" if milieu else consignes

    def _le_milieu(self) -> str:
        """The glossary of the setting, or nothing when there is none."""
        if self.setting is None:
            return ""
        with contextlib.suppress(Exception):
            return str(self.setting())
        return ""

def _empreinte_du_propos(remark: str) -> str:
    """What identifies an already made remark, words aside."""
    import hashlib
    import re

    words = " ".join(sorted(set(re.findall(r"\w{4,}", remark.lower()))))
    return hashlib.sha256(words.encode("utf-8")).hexdigest()[:12]

def _first_name_in(text: str) -> str:
    """The first name in an answer of the form "it's Marcel"."""
    import re

    tools = {
        "c", "ce", "cette", "est", "c'est", "moi", "c'était", "etait", "était",
        "la", "le", "les", "de", "du", "des", "je", "suis", "s", "il", "elle",
        "on", "a", "ah", "eh", "ben", "bah", "oui", "non", "et", "que", "qui",
        "voix", "personne", "sais", "pas", "alors", "donc", "là", "ici", "là-bas",
    }
    words = [m for m in re.findall(r"[\w'-]+", text, flags=re.UNICODE) if m]
    candidats = [m for m in words if m.lower().strip("'") not in tools and len(m) > 2]
    if len(candidats) != 1:
        return ""
    return str(candidats[0]).strip("'").capitalize()
