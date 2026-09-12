"""Answering somebody preparing a meeting, and keeping what was said.

The conversation refused, outside a meeting, to talk about anything at all: it
wanted a meeting that already existed. What was said in front of it was lost,
and the meeting then started from nothing.
"""

from __future__ import annotations

from greffier.application.prepare import Preparing
from greffier.domain.preparation import Preparation, question_prompt


class Cerveau:
    def __init__(self, reponse="Elle a été décalée à jeudi.", casse=False):
        self.reponse = reponse
        self.casse = casse
        self.recu: list[str] = []

    def write_up(self, text):
        self.recu.append(text)
        if self.casse:
            raise RuntimeError("le rédacteur n'a rien produit")
        return self.reponse


def _une() -> Preparation:
    return Preparation(identifier="2026-09-12_10h00_preparation", subject="recette")


class TestAnsweringOutLoud:
    def test_the_answer_comes_back_and_is_kept(self):
        preparation, answered = Preparing(Cerveau()).answer(
            _une(), "rappelle-moi la dernière réunion")
        assert answered == "Elle a été décalée à jeudi."
        assert preparation.exchanges[-1].asked == "rappelle-moi la dernière réunion"
        assert preparation.exchanges[-1].answered == answered

    def test_it_is_said_aloud_when_there_is_a_voice(self):
        dites: list[str] = []
        Preparing(Cerveau(), speak=dites.append).answer(_une(), "et Jira ?")
        assert dites == ["Elle a été décalée à jeudi."]

    def test_without_a_voice_it_is_only_written(self):
        _, answered = Preparing(Cerveau()).answer(_une(), "et Jira ?")
        assert answered

    def test_a_question_that_fails_is_kept_all_the_same(self):
        """Asking and getting an error must not swallow the question."""
        preparation, answered = Preparing(Cerveau(casse=True)).answer(
            _une(), "va voir dans le dépôt")
        assert answered.startswith("✗")
        assert preparation.exchanges[-1].asked == "va voir dans le dépôt"
        assert preparation.exchanges[-1].answered == ""

    def test_a_voice_that_fails_costs_no_answer(self):
        def muette(_):
            raise OSError("aucun lecteur")

        _, answered = Preparing(Cerveau(), speak=muette).answer(_une(), "et Jira ?")
        assert answered == "Elle a été décalée à jeudi."

    def test_an_empty_question_asks_nothing(self):
        cerveau = Cerveau()
        preparation, answered = Preparing(cerveau).answer(_une(), "   ")
        assert answered == "" and cerveau.recu == []
        assert preparation.exchanges == ()


class TestTakingInASpokenSentence:
    def test_the_cue_says_it_was_heard(self):
        """Hearing nothing at all is indistinguishable from a microphone off."""
        sonneries: list[int] = []
        dit = Preparing(Cerveau(), heard=lambda: sonneries.append(1)).transcribed(
            "  rappelle-moi   la dernière  ")
        assert dit == "rappelle-moi la dernière"
        assert sonneries == [1]

    def test_nothing_said_sounds_nothing(self):
        sonneries: list[int] = []
        assert Preparing(Cerveau(), heard=lambda: sonneries.append(1)).transcribed(" ") == ""
        assert sonneries == []

    def test_a_cue_that_cannot_play_costs_no_sentence(self):
        def muet():
            raise OSError("aucun lecteur")

        assert Preparing(Cerveau(), heard=muet).transcribed("bonjour") == "bonjour"


class TestWhatTheModelIsTold:
    def test_the_question_comes_before_the_material(self):
        """Given four thousand characters first, a model answers the material."""
        amorce = question_prompt(_une().raising("un point"), "[Contexte]", "et alors ?")
        assert amorce.index("et alors ?") < amorce.index("un point")

    def test_it_says_the_meeting_has_not_happened(self):
        """Otherwise the model reports what was decided in a meeting nobody held."""
        amorce = question_prompt(_une(), "", "et alors ?")
        assert "n'a pas encore eu lieu" in amorce
        assert "N'invente aucun propos" in amorce

    def test_the_setting_is_carried(self):
        amorce = question_prompt(_une(), "[Contexte] FAST = formulaire", "et alors ?")
        assert "FAST = formulaire" in amorce
