"""What the model writes when it loses the thread, and what is kept of it.

Ten seconds of muddy audio and it repeats the same clause until the slice runs
out. The sentence lands in the minutes as it is. Measured on 3 797 turns of real
meetings: 23 loop, the worst being the same eight words eighteen times over,
608 characters for ten seconds of speech.
"""

import pytest

from greffier.domain.transcription import REPEATS_ALLOWED, without_loop


class TestTheLoopIsCut:
    def test_the_worst_one_measured(self):
        """Eighteen times round, in a real meeting."""
        boucle = "on est en vacuette de l'année, et " * 18
        assert without_loop(boucle.strip()) == (
            "on est en vacuette de l'année, et on est en vacuette de l'année.")

    def test_a_single_word_repeated(self):
        assert without_loop("Non, non, non, non, non, non, non.") == "Non, non."

    def test_a_clause_of_several_words(self):
        assert without_loop(
            "C'est une bonne idée, c'est une bonne idée, c'est une bonne idée, "
            "c'est une bonne idée."
        ) == "C'est une bonne idée, c'est une bonne idée."

    def test_the_half_turn_at_the_end_goes_too(self):
        """The model stops where the slice stops, rarely on a whole clause."""
        assert without_loop("je suis là, je suis là, je suis là, je suis") == (
            "je suis là, je suis là.")

    def test_a_collapsed_clause_is_not_left_hanging(self):
        assert not without_loop(("bon et " * 9).strip()).endswith("et.")


class TestWhatIsSaidTwiceIsLeftAlone:
    """People repeat themselves, and that is theirs to do."""

    def test_an_ordinary_sentence_is_untouched(self):
        dit = "On parle du sprint et de la recette de demain matin."
        assert without_loop(dit) == dit

    def test_twice_is_emphasis(self):
        dit = "C'est vrai, c'est vrai."
        assert without_loop(dit) == dit

    def test_the_allowance_is_what_it_says(self):
        assert without_loop(("oui, " * REPEATS_ALLOWED).strip(", ")) == (
            ", ".join(["oui"] * REPEATS_ALLOWED))

    def test_a_word_coming_back_in_a_sentence_is_no_loop(self):
        dit = "Le sprint de la semaine prochaine porte sur le sprint suivant."
        assert without_loop(dit) == dit

    @pytest.mark.parametrize("dit", [
        "",
        "Oui.",
        "Non, merci.",
        "   ",
    ])
    def test_what_is_too_short_to_loop(self, dit):
        assert without_loop(dit) == dit


class TestTheShortestClauseWins:
    """A loop on three words is also a loop on six: collapsing the short one
    leaves the least behind."""

    def test_it_does_not_stop_at_the_long_reading(self):
        assert without_loop("la la la la la la la la la") == "la la."


class TestItIsRunOnWhatTheModelReturns:
    """The rule serves nothing if it is not applied where the text arrives."""

    def test_both_transcribers_call_it(self):
        from pathlib import Path

        adapters = Path(__file__).resolve().parents[2] / "src/greffier/adapters"
        for nom in ("transcription_faster_whisper.py", "transcription_whisper_cpp.py"):
            code = (adapters / nom).read_text(encoding="utf-8")
            assert "without_loop(" in code, nom
