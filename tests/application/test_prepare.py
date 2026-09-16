"""Answering somebody preparing a meeting, and keeping what was said.

The conversation refused, outside a meeting, to talk about anything at all: it
wanted a meeting that already existed. What was said in front of it was lost,
and the meeting then started from nothing.
"""

from __future__ import annotations

from greffier.application.prepare import Preparing
from greffier.domain.preparation import Preparation, question_prompt


class TheBrain:
    def __init__(self, answer="Elle a été décalée à jeudi.", broken=False):
        self.answer = answer
        self.broken = broken
        self.received: list[str] = []

    def write_up(self, text):
        self.received.append(text)
        if self.broken:
            raise RuntimeError("le rédacteur n'a rien produit")
        return self.answer


def _one() -> Preparation:
    return Preparation(identifier="2026-09-12_10h00_preparation", subject="recette")


class TestAnsweringOutLoud:
    def test_the_answer_comes_back_and_is_kept(self):
        preparation, answered = Preparing(TheBrain()).answer(
            _one(), "rappelle-moi la dernière réunion")
        assert answered == "Elle a été décalée à jeudi."
        assert preparation.exchanges[-1].asked == "rappelle-moi la dernière réunion"
        assert preparation.exchanges[-1].answered == answered

    def test_it_is_said_aloud_when_there_is_a_voice(self):
        said_ones: list[str] = []
        Preparing(TheBrain(), speak=said_ones.append).answer(_one(), "et Jira ?")
        assert said_ones == ["Elle a été décalée à jeudi."]

    def test_without_a_voice_it_is_only_written(self):
        _, answered = Preparing(TheBrain()).answer(_one(), "et Jira ?")
        assert answered

    def test_a_question_that_fails_is_kept_all_the_same(self):
        """Asking and getting an error must not swallow the question."""
        preparation, answered = Preparing(TheBrain(broken=True)).answer(
            _one(), "va voir dans le dépôt")
        assert answered.startswith("✗")
        assert preparation.exchanges[-1].asked == "va voir dans le dépôt"
        assert preparation.exchanges[-1].answered == ""

    def test_a_voice_that_fails_costs_no_answer(self):
        def silent_one(_):
            raise OSError("aucun lecteur")

        _, answered = Preparing(TheBrain(), speak=silent_one).answer(_one(), "et Jira ?")
        assert answered == "Elle a été décalée à jeudi."

    def test_an_empty_question_asks_nothing(self):
        the_brain = TheBrain()
        preparation, answered = Preparing(the_brain).answer(_one(), "   ")
        assert answered == "" and the_brain.received == []
        assert preparation.exchanges == ()


class TestTakingInASpokenSentence:
    def test_the_cue_says_it_was_heard(self):
        """Hearing nothing at all is indistinguishable from a microphone off."""
        rings_heard: list[int] = []
        said = Preparing(TheBrain(), heard=lambda: rings_heard.append(1)).transcribed(
            "  rappelle-moi   la dernière  ")
        assert said == "rappelle-moi la dernière"
        assert rings_heard == [1]

    def test_nothing_said_sounds_nothing(self):
        rings_heard: list[int] = []
        assert Preparing(TheBrain(), heard=lambda: rings_heard.append(1)).transcribed(" ") == ""
        assert rings_heard == []

    def test_a_cue_that_cannot_play_costs_no_sentence(self):
        def silent():
            raise OSError("aucun lecteur")

        assert Preparing(TheBrain(), heard=silent).transcribed("bonjour") == "bonjour"


class TestWhatTheModelIsTold:
    def test_the_question_comes_before_the_material(self):
        """Given four thousand characters first, a model answers the material."""
        seed = question_prompt(_one().raising("un point"), "[Contexte]", "et alors ?")
        assert seed.index("et alors ?") < seed.index("un point")

    def test_it_says_the_meeting_has_not_happened(self):
        """Otherwise the model reports what was decided in a meeting nobody held."""
        seed = question_prompt(_one(), "", "et alors ?")
        assert "n'a pas encore eu lieu" in seed
        assert "N'invente aucun propos" in seed

    def test_the_setting_is_carried(self):
        seed = question_prompt(_one(), "[Contexte] FAST = formulaire", "et alors ?")
        assert "FAST = formulaire" in seed
