"""What the model writes when it loses the thread, and what is kept of it.

Ten seconds of muddy audio and it repeats the same clause until the slice runs
out. The sentence lands in the minutes as it is. Measured on 3 797 turns of real
meetings: 23 loop, the worst being the same eight words eighteen times over,
608 characters for ten seconds of speech.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greffier.domain.transcription import LONGEST_LOOP, REPEATS_ALLOWED, without_loop

#: mutmut 3.8 runs pytest several times in one process, so Hypothesis sees the
#: second run's class instance as another executor and fails the health check
#: before any example runs. The profile's other settings are kept.
in_one_process = settings(suppress_health_check=[*settings.default.suppress_health_check,
                                                 HealthCheck.differing_executors])

#: Twenty words of a meeting, all different, none of them a conjunction a cut
#: must not end on: a clause made of them is kept whole and closed as it is.
WORDS = [
    "budget", "recette", "sprint", "lundi", "équipe", "client", "serveur",
    "contrat", "projet", "réunion", "livraison", "version", "mardi", "test",
    "dossier", "planning", "réponse", "facture", "tableau", "voiture",
]


@st.composite
def a_loop_in_a_sentence(draw):
    """Up to four words, a clause of one to twelve said three to six times, then
    either up to four other words or the start of the clause once more, the
    way the model stops mid-clause when the slice ends."""
    width = draw(st.integers(1, LONGEST_LOOP))
    before = draw(st.integers(0, 4))
    after = draw(st.integers(0, 4))
    words = draw(st.permutations(WORDS))
    prefix = words[:before]
    clause = words[before:before + width]
    suffix = words[before + width:before + width + after]
    fragment = draw(st.integers(0, width - 1)) if not suffix else 0
    repeats = draw(st.integers(REPEATS_ALLOWED + 1, 6))
    return prefix, clause, repeats, clause[:fragment], suffix


class TestTheLoopIsCut:
    def test_the_worst_one_measured(self):
        """Eighteen times round, in a real meeting."""
        loop = "on est en vacuette de l'année, et " * 18
        assert without_loop(loop.strip()) == (
            "on est en vacuette de l'année, et on est en vacuette de l'année.")

    def test_a_single_word_repeated(self):
        assert without_loop("Non, non, non, non, non, non, non.") == "Non, non."

    def test_a_clause_of_several_words(self):
        assert without_loop(
            "C'est une bonne idée, c'est une bonne idée, c'est une bonne idée, "
            "c'est une bonne idée."
        ) == "C'est une bonne idée, c'est une bonne idée."

    def test_three_times_is_where_the_loop_begins(self):
        """Twice is a person insisting, three times is the model."""
        assert without_loop("non non non") == "non non."

    def test_the_half_turn_at_the_end_goes_too(self):
        """The model stops where the slice stops, rarely on a whole clause."""
        assert without_loop("je suis là, je suis là, je suis là, je suis") == (
            "je suis là, je suis là.")

    def test_a_single_word_left_over_goes_too(self):
        assert without_loop("je suis là, je suis là, je suis là, je") == (
            "je suis là, je suis là.")

    def test_a_word_after_the_loop_that_does_not_start_it_again_stays(self):
        assert without_loop("je suis là, je suis là, je suis là, bon.") == (
            "je suis là, je suis là, bon.")

    def test_what_follows_the_loop_stays(self):
        assert without_loop("Non, non, non, non, ça va.") == "Non, non, ça va."

    def test_a_loop_after_an_opening_word_is_cut_to_twice_as_well(self):
        """Measured before the fix: with « Bon, » in front the clause stayed
        three times. The scan moved on by whole clauses from the first word and
        met the loop out of phase, one clause kept before the cut, two after."""
        said = "Bon, " + "on est en vacuette de l'année, " * 4 + "voilà."
        assert without_loop(said) == (
            "Bon, on est en vacuette de l'année, on est en vacuette de l'année, voilà.")

    def test_a_collapsed_clause_is_not_left_hanging(self):
        assert without_loop(("bon et " * 9).strip()) == "bon et bon."


class TestWhateverSurroundsTheLoop:
    """The words before and after a loop are what the person actually said."""

    @in_one_process
    @given(a_loop_in_a_sentence())
    def test_the_clause_is_said_twice_and_the_rest_stays(self, sentence):
        prefix, clause, repeats, fragment, suffix = sentence
        said = " ".join(prefix + clause * repeats + fragment + suffix)
        assert without_loop(said) == (
            " ".join(prefix + clause * REPEATS_ALLOWED + suffix) + ".")

    @in_one_process
    @given(st.integers(1, LONGEST_LOOP), st.permutations(WORDS))
    def test_a_clause_said_twice_is_emphasis_whatever_its_length(self, width, words):
        """Followed by the rest of the sentence, so that a clause of that
        length is looked for at all: a loop needs three times its words."""
        said = " ".join(words[:width] * REPEATS_ALLOWED + words[width:])
        assert without_loop(said) == said

    @in_one_process
    @given(st.lists(st.sampled_from(WORDS), unique=True))
    def test_a_sentence_that_repeats_nothing_is_untouched(self, words):
        said = " ".join(words)
        assert without_loop(said) == said


class TestHowLongAClauseMayBe:
    """Past a dozen words the run is a person making the same point twice."""

    DOZEN = "on reprend le point sur le budget de la recette de demain, "

    def test_a_dozen_words_is_still_a_loop(self):
        assert len(self.DOZEN.split()) == LONGEST_LOOP
        assert without_loop((self.DOZEN * 3).strip()) == (
            "on reprend le point sur le budget de la recette de demain, "
            "on reprend le point sur le budget de la recette de demain.")

    def test_thirteen_words_is_a_person_making_a_point(self):
        said = (self.DOZEN.replace("demain,", "demain matin,") * 3).strip()
        assert len(said.split()) == 3 * (LONGEST_LOOP + 1)
        assert without_loop(said) == said


class TestWhatIsSaidTwiceIsLeftAlone:
    """People repeat themselves, and that is theirs to do."""

    def test_an_ordinary_sentence_is_untouched(self):
        said = "On parle du sprint et de la recette de demain matin."
        assert without_loop(said) == said

    def test_twice_is_emphasis(self):
        said = "C'est vrai, c'est vrai."
        assert without_loop(said) == said

    def test_twice_in_the_middle_of_an_unfinished_sentence_is_emphasis_too(self):
        """Long enough for a two-word clause to be looked for, and without a
        full stop, so that a cut that should not happen would show its mark."""
        said = "C'est vrai, c'est vrai, on y va demain"
        assert without_loop(said) == said

    def test_the_allowance_is_what_it_says(self):
        assert without_loop(("oui, " * REPEATS_ALLOWED).strip(", ")) == (
            ", ".join(["oui"] * REPEATS_ALLOWED))

    def test_a_word_coming_back_in_a_sentence_is_no_loop(self):
        said = "Le sprint de la semaine prochaine porte sur le sprint suivant."
        assert without_loop(said) == said

    @pytest.mark.parametrize("said", [
        "",
        "Oui.",
        "Non, merci.",
        "   ",
    ])
    def test_what_is_too_short_to_loop(self, said):
        assert without_loop(said) == said


class TestTheShortestClauseWins:
    """A loop on three words is also a loop on six: collapsing the short one
    leaves the least behind."""

    def test_it_does_not_stop_at_the_long_reading(self):
        assert without_loop("la la la la la la la la la") == "la la."


class TestHowTheCutEnds:
    """A collapsed sentence ends where it was cut, not on a comma."""

    def test_a_clause_already_closed_is_not_closed_twice(self):
        assert without_loop("Non. Non. Non. Non.") == "Non. Non."

    def test_a_conjunction_hanging_on_an_ellipsis_goes_too(self):
        assert without_loop("on y va, et… on y va, et… on y va, et…") == (
            "on y va, et… on y va.")

    def test_the_cut_takes_the_punctuation_and_leaves_the_letters(self):
        """« Mac OS X » ends on a letter that happens to be a capital."""
        assert without_loop(("on passe sur Mac OS X, " * 4).strip()) == (
            "on passe sur Mac OS X, on passe sur Mac OS X.")
        assert without_loop(("sous Mac OS X, et " * 3).strip()) == (
            "sous Mac OS X, et sous Mac OS X.")


class TestItIsRunOnWhatTheModelReturns:
    """The rule serves nothing if it is not applied where the text arrives."""

    def test_both_transcribers_call_it(self):
        from pathlib import Path

        adapters = Path(__file__).resolve().parents[2] / "src/greffier/adapters"
        for name in ("transcription_faster_whisper.py", "transcription_whisper_cpp.py"):
            code = (adapters / name).read_text(encoding="utf-8")
            assert "without_loop(" in code, name
