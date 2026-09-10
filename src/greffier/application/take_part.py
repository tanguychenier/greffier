"""Faire de l'assistant un participant, et non un micro posé sur la table.

Ce module assemble trois choses que le reste du projet fournit déjà : ce qui se
dit (le fil du direct), une règle qui décide s'il vaut la peine de parler
(`domaine.participation`), et de quoi formuler puis prononcer. Il n'en connaît
aucune : tout arrive par des ports, ce qui permet d'éprouver le comportement
sans lancer de réunion, sans modèle et sans son.

Le tour de force n'est pas de parler, c'est de se taire. Un assistant vocal
ordinaire répond dès qu'on lui laisse un blanc ; en réunion, cela revient à
couper la parole toutes les dix secondes. La règle de `Politique` fait le tri,
et ce module ne fait qu'appliquer sa décision.

Un cycle complet, celui qui vaut d'exister :

    l'assistant   « Je n'arrive plus à distinguer deux voix. Qui vient de parler ? »
    quelqu'un     « c'est Marcel »
    l'assistant   « Merci, c'est noté : je mets Marcel sur cette voix. »

La réponse ne se perd pas dans le fil : elle **nomme la voix**, donc elle sert
au compte rendu et à la banque, ce qui est tout l'intérêt d'avoir demandé.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from greffier.domain.models import Utterance
from greffier.domain.participation import (
    Because,
    Manners,
    Opening,
    called_by_name,
    question_asked,
    speech_density,
)

CONSIGNES_ORALES = """Tu t'appelles {name} et tu participes à une réunion de
travail. On t'entend par un haut-parleur : ce que tu écris sera prononcé tel
quel, à voix haute, devant les participants.

Réponds en **une à deux phrases**. Jamais de liste, de titre, de tableau, de
Markdown, d'URL ni de parenthèse : rien de tout cela ne s'entend. Pas de
préambule, pas de « bien sûr », pas de formule d'attente.

Tu parles à des gens qui sont en train de travailler. Si tu n'as pas la réponse
dans ce qui a été dit, dis-le en une phrase plutôt que de meubler. Si on ne te
posait pas vraiment de question, dis-le brièvement et rends la parole.

N'emploie ni tiret cadratin ni demi-cadratin.
"""

CONTEXTE_MAXIMAL = 6000

RIEN = "RIEN"

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
    """Ce qui prononce. `VoixNeuronale` et `VoixSysteme` s'y conforment."""

    def say(self, text: str) -> bool:
        ...

    def go_quiet(self) -> None:
        ...

    def is_speaking(self) -> bool:
        ...

@dataclass(frozen=True, slots=True)
class Remark:
    """Ce que l'assistant a dit, et pourquoi."""

    remark: str
    because: Because
    a: float
    prononce: bool = False

@dataclass
class AssistantSettings:
    """Écoute la réunion, et y prend la parole quand cela vaut la peine."""

    name: str = "Greffier"
    manners: Manners = field(default_factory=Manners)
    voice: Speaker | None = None
    cerveau: Any | None = None
    context: Callable[[], str] | None = None
    tracer: Callable[[str, str], None] | None = None
    awaiting: Opening | None = None
    name_voice: Callable[[str, str], bool] | None = None
    in_reserve: Opening | None = None
    its_own_turns: list[tuple[float, float]] = field(default_factory=list)
    _job: threading.Thread | None = None
    _search: threading.Thread | None = None

    def turn(
        self,
        utterances: list[Utterance],
        now: float,
        turns: list[tuple[float, float]] | None = None,
        occasions: list[Opening] | None = None,
    ) -> Opening | None:
        """Ce que l'assistant retient de cette tranche, ou rien.

        Rien est le cas courant et c'est voulu : sur une réunion d'une heure,
        cette fonction rendra `None` la quasi-totalité du temps.
        """
        proposees = list(occasions or [])
        for utterance in utterances:
            text = utterance.text.strip()
            if not text or self._is_his_own(utterance):
                continue
            if self.awaiting is not None:
                accuse = self._acknowledge(text, utterance.span.end)
                if accuse is not None:
                    return accuse
            if called_by_name(text, self.name):
                proposees.append(Opening(
                    because=Because.APPELE,
                    remark=question_asked(text, self.name) or text,
                    born_at=utterance.span.end,
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
        """Cherche, dans un fil séparé, s'il y a lieu de dire quelque chose.

        À côté de la boucle qui transcrit : l'appel au modèle prend plusieurs
        secondes, et les passer à attendre coûterait autant d'audio non
        transcrit. Le résultat attend en réserve et sert à la tranche suivante.
        """
        if self.in_reserve is not None or not self.manners.active:
            return
        if self._search is not None and self._search.is_alive():
            return

        def chercher() -> None:
            self.in_reserve = self.contribution(now)

        self._search = threading.Thread(target=chercher, daemon=True)
        self._search.start()

    def _is_his_own(self, utterance: Utterance) -> bool:
        """La réplique tombe-t-elle sur un moment où l'assistant parlait ?

        Il s'entend par le micro de la salle comme tout le monde. Se relire
        soi-même, c'est se répondre, et c'est aussi se donner une voix dans le
        compte rendu.
        """
        start, end = utterance.span.start, utterance.span.end
        return any(
            min(end, sa_fin) - max(start, son_debut) > 0.5 * (end - start)
            for son_debut, sa_fin in self.its_own_turns
        )

    def _lull(self, utterances: list[Utterance], now: float) -> float:
        """Depuis combien de temps plus personne ne parle."""
        if not utterances:
            return now
        return max(0.0, now - max(r.span.end for r in utterances))

    def _acknowledge(self, text: str, a: float) -> Opening | None:
        """Traite la phrase qui répond à la question posée.

        Une question posée et jamais reprise vaut moins que pas de question :
        elle a coûté une interruption pour rien, et celui qui a répondu ne sait
        pas s'il a été entendu.
        """
        attendue, self.awaiting = self.awaiting, None
        if attendue is None:
            return None
        if attendue.because is Because.VOIX_INDISTINCTE:
            return self._name_from_answer(attendue, text, a)
        return self._follow_up_its_question(attendue, text, a)

    def _name_from_answer(
        self, attendue: Opening, text: str, a: float
    ) -> Opening | None:
        """« C'est Hubert » devient un nom porté au compte rendu."""
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
        """Réagit à la réponse qu'on vient de lui faire, ou se tait.

        C'est ce qui sépare un échange d'une question jetée : « très bien, donc
        c'est Hubert qui s'en occupe » prouve qu'elle a compris et laisse une
        trace juste dans le compte rendu. Le silence reste proposé par défaut :
        deux répliques de plus feraient d'elle un participant de trop.
        """
        if self.cerveau is None:
            return None
        guidance = CONSIGNES_SUITE.format(
            name=self.name, rien=RIEN, question=attendue.remark, exemple="Hubert")
        try:
            remark = self._interrogate(guidance, text)
        except (RuntimeError, OSError):
            return None
        if not remark or remark.strip().upper().startswith(RIEN):
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
        """Formule puis prononce. Bloquant : voir `repondre_a_part`."""
        remark = self._phrase_it(opening)
        if not remark:
            return Remark(remark="", because=opening.because, a=now)
        prononce = bool(self.voice and self.voice.say(remark))
        if prononce:
            self.its_own_turns.append((now, now + 1.0 + len(remark) / 15.0))
        self.manners.has_spoken(opening, now)
        if self.tracer is not None:
            with contextlib.suppress(OSError):
                self.tracer(self.name.lower(), remark)
        return Remark(remark=remark, because=opening.because, a=now,
                            prononce=prononce)

    def answer_aside(self, opening: Opening, now: float) -> None:
        """Répond dans un fil séparé, pour ne pas retarder la transcription.

        Formuler demande un appel au modèle, donc plusieurs secondes. Les passer
        à attendre, c'est autant d'audio non transcrit, et le direct ne rattrape
        jamais son retard.
        """
        if self._job is not None and self._job.is_alive():
            return
        self._job = threading.Thread(
            target=self.answer, args=(opening, now), daemon=True)
        self._job.start()

    def _phrase_it(self, opening: Opening) -> str:
        """Le propos exact à prononcer.

        Ce que l'assistant sait dire seul, il le dit seul : demander qui parle
        n'a pas besoin d'un modèle, et faire dépendre cette question d'un appel
        distant la rendrait lente et faillible là où elle doit être immédiate.
        """
        if opening.as_is or opening.because is not Because.APPELE:
            return opening.remark
        if self.cerveau is None:
            return opening.remark
        material = ""
        if self.context is not None:
            with contextlib.suppress(OSError):
                material = str(self.context())[-CONTEXTE_MAXIMAL:]
        demande = (
            f"Voici ce qui s'est dit jusqu'ici dans la réunion :\n\n{material}\n\n"
            f"On vient de te dire : « {opening.remark} »\n\nRéponds."
        )
        try:
            return str(self.cerveau.write_up(demande)).strip()
        except (RuntimeError, OSError):
            return ""

    def contribution(self, now: float) -> Opening | None:
        """Ce que l'assistant aurait à ajouter de lui-même, ou rien.

        Rien est le cas courant, et la consigne le dit crûment : un modèle à
        qui l'on demande « as-tu quelque chose à dire » trouve toujours quelque
        chose à dire, et c'est exactement le défaut qu'on cherche à éviter.
        La politique décidera ensuite si le moment s'y prête ; ici on décide
        seulement s'il y a matière.

        L'appel n'a lieu que quand le repos est écoulé : le demander à chaque
        tranche coûterait un appel toutes les dix secondes pour un silence.
        """
        if self.cerveau is None or self.context is None:
            return None
        if self.manners.parle_le is not None and (
                now - self.manners.parle_le < self.manners.rest):
            return None
        try:
            material = str(self.context())[-CONTEXTE_MAXIMAL:]
        except OSError:
            return None
        if not material.strip():
            return None
        guidance = CONSIGNES_APPORT.format(name=self.name, rien=RIEN)
        try:
            remark = self._interrogate(guidance, material)
        except (RuntimeError, OSError):
            return None
        if not remark or remark.strip().upper().startswith(RIEN):
            return None
        return Opening(
            because=Because.CONTRIBUTION,
            remark=remark,
            born_at=now,
            subject=f"apport:{_empreinte_du_propos(remark)}",
        )

    def _interrogate(self, guidance: str, material: str) -> str:
        """Un appel au cerveau, avec des consignes qui ne sont pas les siennes.

        Le rédacteur porte les consignes de l'oral ; celles de l'apport sont
        différentes, et il ne faut pas que les poser laisse le rédacteur changé
        pour l'appel suivant.
        """
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
        """La question qui règle le problème le plus coûteux de l'outil.

        Une voix non identifiée devient « Personne 12 » dans le compte rendu, et
        personne ne la reconnaîtra après coup. La demander sur le moment coûte
        une phrase et vaut un nom.
        """
        return Opening(
            because=Because.VOIX_INDISTINCTE,
            remark="Excusez-moi, je n'arrive pas à situer la voix qui vient de "
                   "parler. Est-ce que cette personne peut dire son prénom ?",
            born_at=now,
            subject=f"voix:{voice}",
            as_is=True,
        )

    def guidance(self) -> str:
        return CONSIGNES_ORALES.format(name=self.name)

def _empreinte_du_propos(remark: str) -> str:
    """De quoi reconnaître une remarque déjà faite, aux mots près."""
    import hashlib
    import re

    words = " ".join(sorted(set(re.findall(r"\w{4,}", remark.lower()))))
    return hashlib.sha256(words.encode("utf-8")).hexdigest()[:12]

def _first_name_in(text: str) -> str:
    """Le prénom d'une réponse du genre « c'est Marcel » ou « Marcel ».

    Volontairement simple : la réponse à « qui vient de parler » est courte, et
    tout mot qui n'est pas un mot-outil y est un prénom. Une réponse alambiquée
    ne donnera rien, ce qui vaut mieux que de nommer une voix « Alors ».
    """
    import re

    outils = {
        "c", "ce", "cette", "est", "c'est", "moi", "c'était", "etait", "était",
        "la", "le", "les", "de", "du", "des", "je", "suis", "s", "il", "elle",
        "on", "a", "ah", "eh", "ben", "bah", "oui", "non", "et", "que", "qui",
        "voix", "personne", "sais", "pas", "alors", "donc", "là", "ici", "là-bas",
    }
    words = [m for m in re.findall(r"[\w'-]+", text, flags=re.UNICODE) if m]
    candidats = [m for m in words if m.lower().strip("'") not in outils and len(m) > 2]
    if len(candidats) != 1:
        return ""
    return str(candidats[0]).strip("'").capitalize()
