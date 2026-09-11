"""What the tool may ask about, and above all what it keeps quiet about.

A queue of questions that asks one per sentence does not get read: it gets
closed. The false positives measured on this machine's real vocabulary are
therefore pinned down here, just as much as the true ones.
"""

import pytest

from greffier.domain.questions import (
    DISTANCE_MAXIMUM,
    QUESTIONS_MAXIMUM,
    Questioner,
    Reason,
    distance,
    tolerance,
)


class TestTheEditDistance:
    def test_two_identical_words_are_at_zero(self):
        assert distance("backlog", "backlog") == 0

    def test_a_transposition_counts_for_one(self):
        """A transcription swaps two letters: it is the same word.

        Without that, "bakclog"/"backlog" was worth 2, level with
        "point"/"sprint", and no threshold could separate the two cases.
        """
        assert distance("bakclog", "backlog") == 1

    def test_one_letter_more_counts_for_one(self):
        assert distance("ouasis", "oasis") == 1

    def test_two_unrelated_words_stay_far_apart(self):
        assert distance("point", "sprint") == 2


class TestHowMuchIsTolerated:
    def test_a_short_term_accepts_one_difference(self):
        assert tolerance("sprint") == 1

    def test_a_long_term_accepts_two(self):
        assert tolerance("infrastructure") == 2


class TestWhatRaisesAQuestion:
    def test_a_mangled_term_is_picked_up(self):
        questions = Questioner(known=("backlog",)).examine("Le bakclog est plein.")
        assert len(questions) == 1
        assert questions[0].expected == "backlog"
        assert questions[0].heard == "bakclog"
        assert questions[0].motif is Reason.NEAR_TERM

    def test_a_compound_term_is_read_word_by_word(self):
        """"mrege" never met "merge request" and went unnoticed."""
        questions = Questioner(known=("merge request",)).examine("La mrege request.")
        assert questions and questions[0].expected == "merge"

    def test_the_question_says_what_it_heard(self):
        """A question with no reason looks like a whim: nobody answers it."""
        question = Questioner(known=("Oasis",)).examine("Point sur Ouasis.")[0]
        assert "Ouasis" in question.text
        assert "Oasis" in question.text


class TestWhatMustRaiseNothing:
    def test_an_everyday_word_does_not_become_a_term(self):
        """Measured: "point" and "sprint" are at 2 and have nothing to do with each other."""
        assert Questioner(known=("sprint",)).examine("On reprend le point.") == []

    def test_a_term_transcribed_right_asks_nothing(self):
        assert Questioner(known=("backlog",)).examine("Le backlog est trié.") == []

    def test_a_merely_unknown_word_is_no_signal(self):
        """A meeting holds dozens of them, all legitimate."""
        assert Questioner(known=("backlog",)).examine("On parle de Kubernetes.") == []

    def test_short_words_are_dropped(self):
        """"CR" and "OR" are at 1 and have nothing to do with each other."""
        assert Questioner(known=("prod",)).examine("Le brod du truc.") == []

    def test_the_same_question_is_not_asked_twice(self):
        questioner = Questioner(known=("backlog",))
        assert questioner.examine("Le bakclog est plein.")
        assert questioner.examine("Le bakclog encore.") == []

    def test_the_tool_ends_up_going_quiet(self):
        """Past a certain number it would drown whoever is working."""
        known = tuple(f"terme{n:03d}" for n in range(40))
        questioner = Questioner(known=known)
        sentence = " ".join(f"terme{n:03d}x" for n in range(40))
        assert len(questioner.examine(sentence)) <= QUESTIONS_MAXIMUM


class TestAPluralIsNotAMangling:
    """Three questions out of four were of this kind, and absurd.

    Taken from a real meeting: *J'ai entendu "bailleurs". Fallait-il comprendre
    "bailleur" ?*, *J'ai entendu "pre-prod". Fallait-il comprendre "pré-prod" ?*
    A distance of one, so under the threshold, so asked, and pointless, since the
    answer is already known and corrects nothing. The cost is not the question: it
    is that people stop reading the others.
    """

    @pytest.mark.parametrize("heard,connu", [
        ("bailleurs", "bailleur"),
        ("serveurs", "serveur"),
        ("recettes", "recette"),
        ("pre-prod", "pré-prod"),
        ("PRE-PROD", "pré-prod"),
        ("Backlog", "backlog"),
        ("sprints", "sprint"),
    ])
    def test_no_question_about_a_variant(self, heard, connu):
        from greffier.domain.questions import Questioner

        assert Questioner(known=[connu]).examine(f"on parle du {heard}") == []

    @pytest.mark.parametrize("heard,connu", [
        ("Ouasis", "Oasis"),
        ("bakclog", "backlog"),
        ("Coppernic", "Copernic"),
    ])
    def test_a_real_mangling_is_still_picked_up(self, heard, connu):
        """The fix must not carry away the very thing the tool exists for."""
        from greffier.domain.questions import Questioner

        asked = Questioner(known=[connu]).examine(f"on parle de {heard}")
        assert len(asked) == 1 and asked[0].expected == connu

    def test_the_exact_term_raises_nothing(self):
        from greffier.domain.questions import Questioner

        assert Questioner(known=["Oasis"]).examine("on parle d'Oasis") == []


class TestTheCanonicalForm:
    """It serves only to keep quiet, never to identify."""

    def test_it_strips_what_does_not_change_the_word(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("Pré-Prods") == canonical_form("pre prod")

    def test_it_does_not_confuse_two_distinct_terms(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("Oasis") != canonical_form("Ouasis")


class TestWhatRecursIsNoAccident:
    """A mangling does not repeat itself identically.

    The model returns "s'enature" once, not three times. A French word comes back,
    and that is what separates "marge", which is a word, from "merve", which is
    not, with no need for a dictionary the domain does not have.
    """

    def test_a_word_heard_twice_is_no_longer_asked_about(self):
        from greffier.domain.questions import Questioner

        questioner = Questioner(known=["merge"])
        questioner.examine("il reste de la marge sur ce sprint")
        questioner.examine("on garde cette marge pour la dette")
        questioner.examine("la marge sert à absorber les retours")
        # The first occurrence was allowed its question; the later ones are not.
        assert len(questioner.asked) <= 1

    def test_a_term_already_transcribed_right_silences_its_neighbours(self):
        """If the model can spell "merge", it did not mangle it here."""
        from greffier.domain.questions import Questioner

        questioner = Questioner(known=["merge"])
        questioner.examine("j'ai fait le merge ce matin")
        assert questioner.examine("il reste de la marge") == []

    def test_a_lone_mangling_is_still_picked_up(self):
        from greffier.domain.questions import Questioner

        asked = Questioner(known=["signature"]).examine(
            "la s'enature n'est pas passée")
        assert len(asked) == 1 and asked[0].expected == "signature"


class TestADerivedWord:
    """A term with a prefix in front is another word, not a mistake."""

    @pytest.mark.parametrize("heard,connu", [
        ("rétablissements", "établissement"),
        ("reprod", "prod"),
        ("déploiement", "ploiement"),
    ])
    def test_a_derived_word_raises_nothing(self, heard, connu):
        from greffier.domain.questions import derived_word

        assert derived_word(heard, connu)

    def test_the_elision_counts(self):
        """"ré-" before a vowel gives "rétablissement".

        Without it, the case that called for the rule slipped through.
        """
        from greffier.domain.questions import derived_word

        assert derived_word("rétablissement", "établissement")

    @pytest.mark.parametrize("heard,connu", [
        ("Ouasis", "Oasis"),
        ("merde", "merge"),
        ("bakclog", "backlog"),
    ])
    def test_a_mangling_is_not_a_derived_word(self, heard, connu):
        from greffier.domain.questions import derived_word

        assert not derived_word(heard, connu)

    def test_a_false_positive_costs_only_a_silence(self):
        """"recette" passes for "re" + "cette", and that is owned.

        The rule serves only to keep quiet: not asking a question costs less than
        asking an absurd one, and "cette" has no business in a trade vocabulary.
        """
        from greffier.domain.questions import derived_word

        assert derived_word("recette", "cette")


class TestTheEditDistanceIsTheOneItClaims:
    """Optimal string alignment, and not the unrestricted Damerau-Levenshtein.

    The two differ when a stretch is edited twice. On the words of a real
    meeting the unrestricted form brings "ans" and "n'as" to a distance of two,
    which is close enough to ask whether one was misheard for the other. The
    hand-written version this replaces was the aligned one; the library offers
    both, and the wrong one would put a question to the room.
    """

    def test_a_transposition_counts_for_one(self):
        assert distance("bakclog", "backlog") == 1

    def test_two_words_that_only_look_alike_stay_apart(self):
        assert distance("ans", "n'as") > DISTANCE_MAXIMUM

    def test_it_gives_up_above_the_ceiling(self):
        """Whatever the true distance is, past the ceiling nothing is decided
        on it, so counting further would be spent for nothing."""
        assert distance("azerty", "poiuyt") == DISTANCE_MAXIMUM + 1

    def test_the_empty_word_is_at_its_length(self):
        assert distance("", "ab") == 2

    def test_it_does_not_depend_on_the_order(self):
        for one, other in (("recette", "recettes"), ("oasis", "ouasis"),
                           ("prod", "pré-prod"), ("", "a")):
            assert distance(one, other) == distance(other, one)
