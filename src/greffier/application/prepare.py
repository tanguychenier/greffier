"""Answering somebody who is preparing a meeting, and keeping what was said.

The conversation refused, outside a meeting, to talk about anything: it wanted a
meeting that already existed. What was gathered in front of it was lost, and the
meeting then started from nothing -- which is the whole defect this answers.

Everything here is orchestration. What is said to the model is decided by the
domain, where it is kept by an adapter, and who speaks the answer aloud is a
port like any other.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from greffier.domain.preparation import Preparation, question_prompt
from greffier.ports import outbound


@dataclass
class Preparing:
    """One exchange of a preparation, written or spoken."""

    brain: outbound.Writer
    #: The glossary and what earlier meetings left, built where those live.
    setting: str = ""
    known: str = ""
    #: Played the moment a spoken sentence has been taken in. Alone in front of
    #: a machine, hearing nothing at all is indistinguishable from a microphone
    #: that is off.
    heard: Callable[[], None] | None = None
    #: Says the answer out loud. Absent, the answer is only written.
    speak: Callable[[str], None] | None = None

    def transcribed(self, said: str) -> str:
        """Acknowledges a sentence taken in, and hands it back cleaned."""
        propre = " ".join(said.split())
        if propre and self.heard is not None:
            with contextlib.suppress(Exception):
                self.heard()
        return propre

    def answer(
        self, preparation: Preparation, question: str
    ) -> tuple[Preparation, str]:
        """Answers, says it aloud, and keeps the exchange in the preparation.

        The exchange is kept whatever happens, the failure included: somebody
        who asked a question and got an error must find the question again, not
        discover that it was swallowed.
        """
        demande = " ".join(question.split())
        if not demande:
            return preparation, ""
        try:
            answered = str(self.brain.write_up(
                question_prompt(preparation, self.setting + self.known, demande)
            )).strip()
        except Exception as trouble:  # noqa: BLE001 - rendu à qui a demandé
            return preparation.asked(demande), f"✗ {trouble}"
        if answered and self.speak is not None:
            with contextlib.suppress(Exception):
                self.speak(answered)
        return preparation.asked(demande, answered), answered
