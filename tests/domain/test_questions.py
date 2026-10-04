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

    def test_eight_letters_is_where_the_second_difference_is_allowed(self):
        assert tolerance("frontend") == DISTANCE_MAXIMUM
        assert tolerance("backend") == 1


_TWENTY_ONE_TERMS = tuple(f"terme{a}{b}" for a in "abcdefg" for b in "abc")


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

    def test_a_short_term_in_the_list_does_not_hide_the_ones_after_it(self):
        questions = Questioner(known=("prod", "backlog")).examine("Le bakclog est plein.")
        assert [q.expected for q in questions] == ["backlog"]

    def test_on_a_tie_the_term_declared_first_is_the_one_proposed(self):
        """"Spring" is one letter from "sprint" and one from "string": the order of the
        context file decides, so that the same meeting asks the same question."""
        questions = Questioner(known=("sprint", "string")).examine("on parle de Spring")
        assert [q.expected for q in questions] == ["sprint"]

    def test_questions_are_numbered_in_the_order_they_are_asked(self):
        questioner = Questioner(known=("backlog", "Oasis", "sprint"))
        first = questioner.examine("Le bakclog et Ouasis.")
        second = questioner.examine("Et le sprnit.")
        assert [q.number for q in first + second] == [1, 2, 3]

    def test_a_version_number_is_part_of_the_term(self):
        """"Python3" is one term, not "Python3" and "Python"."""
        assert Questioner(known=("Python3",)).known == ("Python3",)


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
        """Past a certain number it would drown whoever is working.

        Terms of letters alone, mangled by a letter that is not a plural mark: the
        word pattern drops digits and the canonical form drops a final x, so an
        earlier form of this test, on "terme007" heard as "terme007x", asked no
        question at all and its ceiling held for nothing.
        """
        questioner = Questioner(known=_TWENTY_ONE_TERMS)
        sentence = " ".join(f"{term}z" for term in _TWENTY_ONE_TERMS[:20])
        assert len(questioner.examine(sentence)) == QUESTIONS_MAXIMUM

    def test_once_quiet_a_fresh_mangling_raises_nothing(self):
        questioner = Questioner(known=_TWENTY_ONE_TERMS)
        questioner.examine(" ".join(f"{term}z" for term in _TWENTY_ONE_TERMS[:20]))
        assert questioner.examine(f"{_TWENTY_ONE_TERMS[20]}z") == []


class TestAPluralIsNotAMangling:
    """Three questions out of four were of this kind, and absurd.

    Taken from a real meeting: *J'ai entendu "bailleurs". Fallait-il comprendre
    "bailleur" ?*, *J'ai entendu "pre-prod". Fallait-il comprendre "pré-prod" ?*
    A distance of one, so under the threshold, so asked, and pointless, since the
    answer is already known and corrects nothing. The cost is not the question: it
    is that people stop reading the others.
    """

    @pytest.mark.parametrize(("heard", "known_one"), [
        ("bailleurs", "bailleur"),
        ("serveurs", "serveur"),
        ("recettes", "recette"),
        ("pre-prod", "pré-prod"),
        ("PRE-PROD", "pré-prod"),
        ("Backlog", "backlog"),
        ("sprints", "sprint"),
    ])
    def test_no_question_about_a_variant(self, heard, known_one):
        from greffier.domain.questions import Questioner

        assert Questioner(known=[known_one]).examine(f"on parle du {heard}") == []

    @pytest.mark.parametrize(("heard", "known_one"), [
        ("Ouasis", "Oasis"),
        ("bakclog", "backlog"),
        ("Coppernic", "Copernic"),
    ])
    def test_a_real_mangling_is_still_picked_up(self, heard, known_one):
        """The fix must not carry away the very thing the tool exists for."""
        from greffier.domain.questions import Questioner

        asked = Questioner(known=[known_one]).examine(f"on parle de {heard}")
        assert len(asked) == 1 and asked[0].expected == known_one

    def test_the_exact_term_raises_nothing(self):
        from greffier.domain.questions import Questioner

        assert Questioner(known=["Oasis"]).examine("on parle d'Oasis") == []

    def test_a_plural_raises_nothing_even_when_another_term_is_as_close(self):
        """"clients" is the plural of "client"; "cliente" being one letter away changes
        nothing, whatever its place in the list."""
        from greffier.domain.questions import Questioner

        assert Questioner(known=["cliente", "client"]).examine("on livre aux clients") == []


class TestTheCanonicalForm:
    """It serves only to keep quiet, never to identify."""

    def test_it_strips_what_does_not_change_the_word(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("Pré-Prods") == canonical_form("pre prod")

    def test_it_does_not_confuse_two_distinct_terms(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("Oasis") != canonical_form("Ouasis")

    def test_a_hyphen_does_not_make_another_word(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("pré-prod") == canonical_form("preprod")


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

    def test_a_word_said_twice_in_one_sentence_was_meant(self):
        from greffier.domain.questions import Questioner

        assert Questioner(known=["merge"]).examine("la marge, encore la marge") == []

    def test_a_word_that_recurs_does_not_silence_the_mangling_beside_it(self):
        from greffier.domain.questions import Questioner

        questioner = Questioner(known=["merge", "backlog"])
        questioner.examine("il reste de la marge")
        asked = questioner.examine("la marge et le bakclog")
        assert [q.expected for q in asked] == ["backlog"]


class TestADerivedWord:
    """A term with a prefix in front is another word, not a mistake."""

    @pytest.mark.parametrize(("heard", "known_one"), [
        ("rétablissements", "établissement"),
        ("reprod", "prod"),
        ("déploiement", "ploiement"),
    ])
    def test_a_derived_word_raises_nothing(self, heard, known_one):
        from greffier.domain.questions import derived_word

        assert derived_word(heard, known_one)

    def test_the_elision_counts(self):
        """"ré-" before a vowel gives "rétablissement".

        Without it, the case that called for the rule slipped through.
        """
        from greffier.domain.questions import derived_word

        assert derived_word("rétablissement", "établissement")

    @pytest.mark.parametrize(("heard", "known_one"), [
        ("Ouasis", "Oasis"),
        ("merde", "merge"),
        ("bakclog", "backlog"),
    ])
    def test_a_mangling_is_not_a_derived_word(self, heard, known_one):
        from greffier.domain.questions import derived_word

        assert not derived_word(heard, known_one)

    def test_a_prefix_in_front_of_another_word_is_no_derivation(self):
        """"récolte" is not "ré" + "école": what follows the prefix has to be the term."""
        from greffier.domain.questions import derived_word

        assert not derived_word("récolte", "école")

    @pytest.mark.parametrize("word", ["retour", "import", "oasis"])
    def test_nothing_derives_from_an_empty_term(self, word):
        from greffier.domain.questions import derived_word

        assert not derived_word(word, "")

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


class TestAQuestionIsPutToTheRoomOnlyOnce:
    """Measured on the meeting of 11 September: three unanswered questions came
    back into the conversation two and a half hours after the minutes had been
    sent. The window kept what it had shown in memory, the memory died with the
    process, and the state file still named the finished meeting: one copy per
    launch.
    """

    def test_the_note_is_recognised_as_the_question(self):
        from greffier.domain.questions import Question, Reason, already_noted, note

        question = Question(number=1, text="J'ai entendu « merde ».",
                            motif=Reason.NEAR_TERM)
        assert already_noted([question], [note(question.text)]) == {1}

    def test_a_question_never_shown_is_not_held_back(self):
        from greffier.domain.questions import Question, Reason, already_noted

        question = Question(number=1, text="J'ai entendu « merde ».",
                            motif=Reason.NEAR_TERM)
        assert already_noted([question], ["bonjour", "au revoir"]) == set()

    def test_only_the_one_that_was_shown_is_held_back(self):
        """Answering one question must not swallow the next."""
        from greffier.domain.questions import Question, Reason, already_noted, note

        one_ = Question(number=1, text="J'ai entendu « merde ».",
                       motif=Reason.NEAR_TERM)
        other = Question(number=2, text="J'ai entendu « Spring ».",
                         motif=Reason.NEAR_TERM)
        assert already_noted([one_, other], [note(one_.text)]) == {1}

    def test_an_empty_conversation_holds_nothing_back(self):
        from greffier.domain.questions import Question, Reason, already_noted

        question = Question(number=3, text="J'ai entendu « cacher ».",
                            motif=Reason.NEAR_TERM)
        assert already_noted([question], []) == set()

    def test_the_three_of_the_real_meeting(self):
        from greffier.domain.questions import Question, Reason, already_noted, note

        asked = [
            Question(number=2, text="J'ai entendu « Spring ». Fallait-il "
                                    "comprendre « sprint » ?",
                     motif=Reason.NEAR_TERM, heard="Spring", expected="sprint"),
            Question(number=3, text="J'ai entendu « merde ». Fallait-il "
                                    "comprendre « merge » ?",
                     motif=Reason.NEAR_TERM, heard="merde", expected="merge"),
            Question(number=4, text="J'ai entendu « cacher ». Fallait-il "
                                    "comprendre « cachet » ?",
                     motif=Reason.NEAR_TERM, heard="cacher", expected="cachet"),
        ]
        conversation = [note(question.text) for question in asked]
        conversation.append("[greffier] Le compte rendu est prêt.")
        assert already_noted(asked, conversation) == {2, 3, 4}

    def test_the_note_carries_the_question(self):
        from greffier.domain.questions import note

        assert "Fallait-il" in note("Fallait-il comprendre « merge » ?")

    def test_the_keys_of_what_was_asked_survive_a_restart(self):
        """The window comes back with the keys read from the questions file and no
        memory of what was heard: the same mangling must not come back with it."""
        before = Questioner(known=["backlog"])
        assert len(before.examine("Le bakclog est plein.")) == 1
        after = Questioner(known=["backlog"], asked=set(before.asked))
        assert after.examine("Le bakclog est plein.") == []

    def test_a_question_already_placed_does_not_hold_back_the_next_one(self):
        before = Questioner(known=["backlog", "Oasis"])
        before.examine("Le bakclog est plein.")
        after = Questioner(known=["backlog", "Oasis"], asked=set(before.asked))
        assert [q.expected for q in after.examine("Le bakclog et Ouasis.")] == ["Oasis"]
