"""The assistant's manners, covered without starting a meeting."""

from typing import ClassVar

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greffier.domain.participation import (
    MAXIMUM_DENSITY,
    MEMORY_OF_A_CALL,
    MINIMUM_LULL,
    Because,
    Manners,
    Opening,
    called_by_name,
    is_own,
    is_the_same_call,
    own_words,
    question_asked,
    speech_density,
    split_at_the_name,
    without_own_name,
)


def opening(because=Because.CONTRIBUTION, remark="…", born_at=0.0, subject=""):
    return Opening(because=because, remark=remark, born_at=born_at, subject=subject)


# A moment of a two-hour meeting, and a turn as the detector reports one: two
# moments, the earlier first.
MOMENTS = st.floats(min_value=0.0, max_value=7200.0, allow_nan=False, allow_infinity=False)
TURNS = st.lists(
    st.tuples(MOMENTS, MOMENTS).map(lambda pair: (min(pair), max(pair))), max_size=20
)

# mutmut's fork server runs each test a second time in the interpreter that
# already ran it once, on a fresh instance of its class. Hypothesis reads the
# two instances as two executors and fails the test, and that failure is booked
# as a kill the mutant did not earn.
UNDER_MUTMUT = settings(
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.differing_executors]
)


class TestNeverCuttingIn:
    def test_it_keeps_quiet_while_anyone_is_speaking(self):
        """The defect of every voice assistant: answering into the gap.

        A one-second gap in a meeting is not an invitation, it is a breath. Stepping
        into it is cutting somebody off.
        """
        manners = Manners()
        refusal = manners.refusal(opening(), now=10.0, lull=0.5)
        assert refusal == "quelqu'un parle"

    def test_a_real_lull_gives_it_the_floor(self):
        manners = Manners()
        assert manners.refusal(opening(), now=10.0, lull=MINIMUM_LULL) is None

    def test_it_does_not_slip_into_a_tight_exchange(self):
        """Three people talking in turn are not waiting for a fourth opinion."""
        manners = Manners()
        refusal = manners.refusal(opening(born_at=95.0), now=100.0, lull=3.0,
                                density=0.95)
        assert refusal == "la discussion est trop dense"

    def test_a_density_right_at_the_ceiling_still_lets_it_speak(self):
        manners = Manners()
        at_the_ceiling = manners.refusal(opening(born_at=95.0), now=100.0, lull=3.0,
                                         density=MAXIMUM_DENSITY)
        just_over = manners.refusal(opening(born_at=95.0), now=100.0, lull=3.0,
                                    density=MAXIMUM_DENSITY + 0.01)
        assert at_the_ceiling is None
        assert just_over == "la discussion est trop dense"


class TestNeverComingBackTooOften:
    def test_it_rests_after_speaking(self):
        manners = Manners()
        said = opening(born_at=0.0)
        manners.has_spoken(said, now=0.0)
        refusal = manners.refusal(opening(born_at=60.0), now=60.0, lull=5.0)
        assert refusal is not None and "repos" in refusal

    def test_once_the_rest_is_over_it_may_speak_again(self):
        manners = Manners(rest=180.0)
        manners.has_spoken(opening(), now=0.0)
        assert manners.refusal(opening(born_at=200.0), now=200.0, lull=5.0) is None

    def test_being_called_ignores_the_rest(self):
        """Someone addressing the tool expects an answer, not restraint."""
        manners = Manners()
        manners.has_spoken(opening(), now=0.0)
        the_call = opening(because=Because.CALLED, born_at=10.0)
        assert manners.refusal(the_call, now=10.0, lull=0.0, density=1.0) is None

    @UNDER_MUTMUT
    @given(spoke_at=st.integers(min_value=0, max_value=36_000),
           elapsed=st.integers(min_value=0, max_value=179))
    def test_the_refusal_counts_the_rest_down_to_the_second(self, spoke_at, elapsed):
        """Late in the meeting as at its start: what counts is how long ago."""
        manners = Manners(rest=180.0)
        manners.has_spoken(opening(), now=float(spoke_at))
        now = float(spoke_at + elapsed)
        assert manners.refusal(opening(born_at=now), now=now, lull=5.0) == (
            f"il vient de parler, encore {180 - elapsed} s de repos")

    def test_the_rest_ends_at_the_second_it_is_up(self):
        manners = Manners(rest=180.0)
        manners.has_spoken(opening(), now=100.0)
        assert manners.refusal(opening(born_at=279.0), now=279.0, lull=5.0) == (
            "il vient de parler, encore 1 s de repos")
        assert manners.refusal(opening(born_at=280.0), now=280.0, lull=5.0) is None


class TestNeverRepeatingItself:
    def test_a_subject_already_dealt_with_does_not_come_back(self):
        manners = Manners()
        first_one = opening(subject="qui-parle-voix-3", born_at=10.0)
        manners.has_spoken(first_one, now=10.0)
        second_one = opening(subject="qui-parle-voix-3", born_at=400.0)
        assert manners.refusal(second_one, now=400.0, lull=5.0) == "déjà dit"

    def test_even_called_it_does_not_repeat_a_question_asked(self):
        manners = Manners()
        manners.has_spoken(opening(subject="qui-parle-voix-3"), now=0.0)
        the_call = opening(because=Because.CALLED, subject="qui-parle-voix-3", born_at=50.0)
        assert manners.refusal(the_call, now=50.0, lull=9.0) == "déjà dit"

    def test_the_same_call_heard_again_by_the_next_slice_is_not_answered_twice(self):
        manners = Manners()
        manners.has_spoken(opening(because=Because.CALLED, subject="appel:abc"), now=100.0)
        again = opening(because=Because.CALLED, subject="appel:abc", born_at=112.0)
        assert manners.refusal(again, now=112.0, lull=9.0) == "déjà dit"

    def test_the_same_question_asked_again_minutes_later_is_answered(self):
        # Word for word, by somebody who wants it answered again: the
        # subject of a call is the overlap's guard, not the meeting's memory.
        manners = Manners()
        manners.has_spoken(opening(because=Because.CALLED, subject="appel:abc"), now=100.0)
        again = opening(because=Because.CALLED, subject="appel:abc", born_at=300.0)
        assert manners.refusal(again, now=300.0, lull=9.0) is None

    def test_a_subject_nobody_has_dealt_with_is_not_already_said(self):
        manners = Manners()
        fresh = opening(subject="qui-parle-voix-3", born_at=10.0)
        assert manners.refusal(fresh, now=10.0, lull=5.0) is None

    def test_thirty_seconds_to_the_second_the_call_is_still_the_same(self):
        manners = Manners()
        manners.has_spoken(opening(because=Because.CALLED, subject="appel:abc"), now=100.0)
        again = opening(because=Because.CALLED, subject="appel:abc", born_at=130.0)
        assert manners.refusal(again, now=100.0 + MEMORY_OF_A_CALL, lull=9.0) == "déjà dit"
        assert manners.refusal(again, now=100.5 + MEMORY_OF_A_CALL, lull=9.0) is None


class TestNeverServingSomethingCold:
    def test_a_stale_opening_is_dropped(self):
        """Coming back to a subject already left looks like an absent-minded participant."""
        manners = Manners(staleness=90.0)
        old_one = opening(born_at=10.0)
        refusal = manners.refusal(old_one, now=200.0, lull=5.0)
        assert refusal == "la conversation est passée à autre chose"

    def test_a_call_by_name_does_not_go_stale_for_all_that(self):
        manners = Manners()
        the_call = opening(because=Because.CALLED, born_at=10.0)
        assert manners.refusal(the_call, now=500.0, lull=0.0) is None

    def test_an_opening_exactly_as_old_as_the_limit_is_still_served(self):
        manners = Manners(staleness=90.0)
        assert manners.refusal(opening(born_at=10.0), now=100.0, lull=5.0) is None
        assert manners.refusal(opening(born_at=10.0), now=100.5, lull=5.0) == (
            "la conversation est passée à autre chose")


class TestChoosingWhatToSay:
    def test_at_most_one_opening_and_the_strongest(self):
        """The others are dropped, not held in reserve."""
        manners = Manners()
        retained = manners.choose(
            [
                opening(because=Because.CONTRIBUTION, remark="une idée", born_at=10.0),
                opening(because=Because.INDISTINCT_VOICE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.QUESTION_WITHOUT_ANSWER,
                        remark="et Pascal ?", born_at=10.0),
            ],
            now=12.0, lull=5.0,
        )
        assert retained is not None and retained.remark == "qui parle ?"

    def test_on_equal_strength_the_most_recent_one_passes(self):
        manners = Manners()
        retained = manners.choose(
            [opening(remark="vieille", born_at=10.0), opening(remark="fraîche", born_at=50.0)],
            now=60.0, lull=5.0,
        )
        assert retained is not None and retained.remark == "fraîche"

    def test_nothing_to_say_is_an_answer(self):
        manners = Manners()
        assert manners.choose([], now=10.0, lull=5.0) is None

    def test_being_called_comes_before_everything(self):
        manners = Manners()
        retained = manners.choose(
            [
                opening(because=Because.INDISTINCT_VOICE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.CALLED, remark="oui ?", born_at=11.0),
            ],
            now=12.0, lull=0.0, density=1.0,
        )
        assert retained is not None and retained.remark == "oui ?"

    def test_a_dense_discussion_leaves_nothing_to_choose(self):
        """The density reaches `refusal` through `choose`: one rule, judged once."""
        manners = Manners()
        assert manners.choose([opening(born_at=10.0)], now=12.0, lull=5.0, density=0.95) is None


class TestTheButton:
    def test_switched_off_it_says_nothing_at_all(self):
        """The button in the window sets this, and unsets it, as often as wanted."""
        manners = Manners(active=False)
        the_call = opening(because=Because.CALLED, born_at=10.0)
        assert manners.refusal(the_call, now=10.0, lull=9.0) == "il ne participe pas"

    def test_switched_back_on_it_starts_again_without_a_grudge(self):
        manners = Manners(active=False)
        manners.active = True
        assert manners.refusal(opening(born_at=10.0), now=11.0, lull=5.0) is None


class TestWhenSpeakingFails:
    def test_a_phrasing_that_fails_does_not_cost_the_rest(self):
        """`a_parle` is called after the fact: nothing was said, nothing is kept."""
        manners = Manners()
        assert manners.refusal(opening(born_at=10.0), now=11.0, lull=5.0) is None
        assert manners.spoke_at is None


class TestHowDenseTheTalkIs:
    def test_a_full_minute_is_worth_one(self):
        assert speech_density([(0.0, 60.0)], now=60.0) == 1.0

    def test_an_empty_minute_is_worth_zero(self):
        assert speech_density([], now=60.0) == 0.0

    def test_only_the_last_minute_counts(self):
        """A meeting that comes alive must not be judged on its quiet beginning."""
        turns = [(0.0, 300.0), (350.0, 355.0)]
        assert speech_density(turns, now=360.0, window=60.0) < 0.2

    def test_a_turn_astride_counts_only_for_its_share(self):
        assert speech_density([(50.0, 70.0)], now=60.0, window=60.0) == 10.0 / 60.0

    def test_at_the_very_start_there_is_nothing_to_measure(self):
        assert speech_density([], now=0.0) == 0.0

    def test_younger_than_its_window_the_meeting_is_judged_on_what_it_has(self):
        assert speech_density([(0.0, 0.5)], now=0.5) == 1.0

    def test_a_full_minute_late_in_the_meeting_is_still_worth_one(self):
        assert speech_density([(300.0, 360.0)], now=360.0) == 1.0

    def test_a_turn_that_ended_before_the_window_counts_for_nothing(self):
        assert speech_density([(0.0, 10.0)], now=300.0) == 0.0

    def test_the_window_is_a_minute_and_a_second_past_it_is_forgotten(self):
        assert speech_density([(0.0, 1.0)], now=61.0) == 0.0

    def test_two_voices_at_once_do_not_make_more_than_a_full_minute(self):
        assert speech_density([(0.0, 60.0), (0.0, 60.0)], now=60.0) == 1.0

    @UNDER_MUTMUT
    @given(turns=TURNS, now=MOMENTS)
    def test_the_density_is_a_share_between_nothing_and_everything(self, turns, now):
        assert 0.0 <= speech_density(turns, now) <= 1.0


class TestWhatTheSettingGuarantees:
    """The contract as it was asked for: three sentences, three guarantees.

    "If I switch it on: it speaks only when its name is said. When we cut it, it
    does not speak. If it is speaking and we cut it, it does not finish its
    sentence."
    """

    def test_switched_on_it_speaks_only_on_its_name(self):
        """Without the initiative, no spontaneous opening gets through."""
        manners = Manners(active=True)
        idea = Opening(because=Because.CONTRIBUTION, remark="une remarque", born_at=100.0)
        the_call = Opening(because=Because.CALLED, remark="oui ?", born_at=100.0)
        # The contribution is not even looked for when initiative is off: the
        # watch takes care of that. Here the check is that the call itself goes
        # through always, whatever the conditions.
        assert manners.refusal(the_call, now=100.0, lull=0.0, density=1.0) is None
        assert manners.refusal(idea, now=100.0, lull=0.0, density=1.0)

    def test_switched_off_it_says_nothing_at_all(self):
        manners = Manners(active=False)
        for because in Because:
            opening = Opening(because=because, remark="…", born_at=100.0)
            assert manners.refusal(opening, now=100.0, lull=9.0) == (
                "il ne participe pas")


class TestItMustNotHearItself:
    """It speaks through the loudspeaker, and the tool records the system output.

    That is deliberate: it is how it hears the other participants of a video call.
    As a result its own voice comes back on the others' channel, it reads its own
    name in its own answer, and off it goes again. **Without end.**

    Judged on the words and not on the clock, and that is the whole point: it
    answers late, in a separate thread, so no window of time is reliable.
    """

    SAID = "Qui prend en charge la migration en Symfony 7 ?"

    def _its_own_words(self, *remarks: str) -> list[frozenset[str]]:
        return [own_words(r) for r in remarks]

    def test_its_exact_words_come_back(self):
        assert is_own(self.SAID, self._its_own_words(self.SAID))

    def test_its_words_mangled_by_the_loudspeaker(self):
        """What comes back is never spelled the same way."""
        assert is_own(
            "qui prend en charge la migration en Symfony sept",
            self._its_own_words(self.SAID),
        )

    def test_half_of_its_sentence_is_enough(self):
        """The room and the capture loop cost words on the way."""
        assert is_own("qui prend en charge la migration", self._its_own_words(self.SAID))

    def test_the_room_is_not_taken_for_it(self):
        assert not is_own(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?",
            self._its_own_words(self.SAID),
        )

    def test_an_interjection_is_never_its_own(self):
        """"oui" and "d'accord" belong to everybody."""
        for court in ("oui", "d'accord", "bon", "ok"):
            assert not is_own(court, self._its_own_words("oui d'accord bon ok"))

    def test_having_said_nothing_it_hears_nobody(self):
        assert not is_own(self.SAID, [])

    def test_several_of_its_remarks_are_kept(self):
        """She speaks several times: each must stay recognisable."""
        mes = self._its_own_words(
            self.SAID,
            "Il reste la signature, et la recette à caler.",
        )
        assert is_own("il reste la signature et la recette", mes)
        assert is_own("qui prend en charge la migration", mes)

    def test_accents_do_not_make_two_sentences(self):
        assert is_own(
            "L'ETAPE VISA EST DEJA CALEE POUR JEUDI",
            self._its_own_words("L'étape visa est déjà calée pour jeudi"),
        )

    def test_a_shared_subject_is_not_enough(self):
        """The real risk: a participant talking about the same subject it did."""
        assert not is_own(
            "la migration me paraît risquée avant la recette de jeudi soir",
            self._its_own_words("Qui prend en charge la migration ?"),
        )

    def test_three_words_in_five_are_enough(self):
        """Six in ten is the share, and three in five is exactly that."""
        its_own = self._its_own_words(
            "La recette est prête depuis lundi, il manque la signature du prestataire.")
        assert is_own("recette prête lundi bureau mardi", its_own)


class TestItsOwnNameNeverLeavesItsMouth:
    """The hard guarantee, and the one that cuts the loop at the root.

    Seen in a real meeting: "Lucie, est-ce que tu peux faire des recherches sur
    Internet ?" fifteen times in fifteen seconds, spoken by it. It had repeated
    the question it had just been asked, its own name included, heard it through
    the capture loop, read its name in it, and set off again.

    Taking its name out of everything it pronounces makes the cycle impossible,
    whatever else happens: no brain, a mangled transcription, a badly attributed
    channel.
    """

    def test_its_name_is_taken_out(self):
        assert "Lucie" not in without_own_name(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?", "Lucie"
        )

    def test_what_it_says_stays_readable(self):
        assert without_own_name(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?", "Lucie"
        ) == "est-ce que tu peux faire des recherches sur Internet ?"

    def test_its_mangled_name_is_taken_out_too(self):
        """La transcription rend « Lucie » de vingt façons."""
        for said in ("Lucy, tu m'entends ?", "Lucie tu m'entends ?",
                    "Luci, tu m'entends ?"):
            assert "uc" not in without_own_name(said, "Lucie").lower(), said

    def test_a_remark_without_its_name_is_untouched(self):
        """The common case: it must not see its own sentence reworked."""
        the_remarks = "Qui prend en charge la migration en Symfony 7 ?"
        assert without_own_name(the_remarks, "Lucie") == the_remarks

    def test_french_typography_survives(self):
        """French keeps a space before the colon."""
        the_remarks = "Merci, c'est noté : je mets Hubert sur cette voix."
        assert without_own_name(the_remarks, "Lucie") == the_remarks

    def test_the_name_in_the_middle_of_a_sentence(self):
        assert without_own_name("Oui Lucie a bien compris", "Lucie") == "Oui a bien compris"

    def test_an_empty_name_touches_nothing(self):
        assert without_own_name("phrase entière", "") == "phrase entière"

    def test_what_is_left_calls_nobody_any_more(self):
        """The full loop: what she says must no longer call her."""
        for question in (
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?",
            "Lucie, tu as compris le sujet Lucie ?",
            "Dis-moi Lucie",
        ):
            remaining = without_own_name(question, "Lucie")
            assert not called_by_name(remaining, "Lucie"), remaining

    def test_a_short_name_does_not_swallow_a_word_two_edits_away(self):
        """"huit" is two edits from "Hugo": on four letters, half the word."""
        assert without_own_name("il reste huit jours", "Hugo") == "il reste huit jours"
        assert without_own_name("Hugho, tu m'entends ?", "Hugo") == "tu m'entends ?"

    def test_the_comma_the_name_leaves_behind_closes_up(self):
        assert without_own_name("Dis-moi Lucie, on décale ?", "Lucie") == "Dis-moi, on décale ?"
        assert without_own_name("Merci Lucie. On décale.", "Lucie") == "Merci. On décale."


class TestItOnlyAnswersToItsOwnName:
    """It spoke up believing it had been called, and made the room look foolish.

    Measured on 3 809 turns of real meetings, with a five-letter first name: the
    old rule allowed two edits whatever the length, so "lui" named it. **113
    times**, against 75 real calls. Two guards, and each was chosen from that
    measurement rather than from taste.
    """

    def test_the_word_that_cost_the_most_is_refused(self):
        """"lui" is at two edits from "Lucie", and it is a common French word."""
        assert not called_by_name("je lui ai dit qu'on se cale jeudi", "Lucie")

    def test_its_own_name_is_still_heard(self):
        assert called_by_name("Lucie, est-ce que tu nous entends ?", "Lucie")

    def test_a_name_in_the_middle_of_a_sentence_is_heard(self):
        assert called_by_name("on demande à Lucie de vérifier", "Lucie")

    def test_a_lightly_mangled_name_is_still_heard(self):
        """The transcription does not always spell it right."""
        assert called_by_name("Lucye, tu peux regarder ?", "Lucie")

    def test_a_lowercase_word_never_names_it(self):
        """Every one of the 75 real calls was written with a capital, and no
        word that named it wrongly ever was: a first name is a proper noun."""
        assert not called_by_name("on parle de lucie demain", "Lucie")

    def test_a_short_name_demands_more(self):
        """A single edit on three letters is a third of the word."""
        assert called_by_name("Zoé, tu en penses quoi ?", "Zoé")
        assert not called_by_name("Zone rouge sur le planning", "Zoé")

    def test_a_long_name_may_be_mangled_more(self):
        assert called_by_name("Arnaude, tu peux regarder ?", "Arnaud")

    def test_an_empty_name_names_nobody(self):
        assert not called_by_name("Lucie, tu es là ?", "   ")

    def test_taking_the_name_out_stays_generous(self):
        """Stripping is not answering: leaving a mangled name in what it says is
        what made it call itself, and taking out a word that was not its name
        costs nothing."""
        assert "uc" not in without_own_name("Lucy, je regarde.", "Lucie").lower()

    def test_the_tolerance_is_a_quarter_of_the_name(self):
        """Four letters allow one edit and eight allow two: a quarter, not a fifth."""
        assert called_by_name("Hugho, tu es là ?", "Hugo")
        assert not called_by_name("Hughos, tu es là ?", "Hugo")
        assert called_by_name("Jonatane, tu es là ?", "Jonathan")
        assert not called_by_name("Jonatanes, tu es là ?", "Jonathan")


class TestTheQuestionIsWhatFollowsTheName:
    """With the slice ending at a quiet moment, « …en fin de journée. Lucie, à
    quel jour est décalée la recette ? » came as one sentence, and the
    question, already asked by the pass that heard it alone, was asked a
    second time under another fingerprint."""

    def test_what_precedes_the_name_is_context_not_question(self):
        before, asked = split_at_the_name(
            "en fin de journée. Lucie, à quel jour est décalée la recette ?", "Lucie"
        )
        assert before == "en fin de journée."
        assert asked == "à quel jour est décalée la recette ?"

    def test_a_call_that_opens_the_sentence_has_nothing_before(self):
        assert split_at_the_name("Lucie, à quel jour ?", "Lucie") == ("", "à quel jour ?")

    def test_the_last_name_said_is_the_one_that_counts(self):
        before, asked = split_at_the_name("Lucie ? Lucie, tu m'entends ?", "Lucie")
        assert asked == "tu m'entends ?" and before == "Lucie ?"

    def test_a_mangled_name_is_still_the_cut(self):
        assert split_at_the_name("Lucy, on décale ?", "Lucie") == ("", "on décale ?")

    def test_without_the_name_the_whole_sentence_is_the_question(self):
        assert split_at_the_name("on décale ?", "Lucie") == ("", "on décale ?")

    def test_the_mark_that_opens_the_question_is_not_lost_with_the_name(self):
        # Guillemets are not among the marks the tidying strips: dropped with
        # the name, the opening one would leave its closing one alone.
        assert split_at_the_name("Lucie « on décale ? »", "Lucie") == ("", "« on décale ? »")

    def test_a_line_break_or_a_double_space_becomes_one_space(self):
        before, asked = split_at_the_name("en fin de  journée. Lucie, à quel\njour ?", "Lucie")
        assert (before, asked) == ("en fin de journée.", "à quel jour ?")

    def test_a_space_before_a_comma_is_closed_up_on_both_sides(self):
        before, asked = split_at_the_name(
            "en fin de journée , Lucie, à quel jour , dis-moi ?", "Lucie")
        assert (before, asked) == ("en fin de journée,", "à quel jour, dis-moi ?")


class TestTheSameQuestionHeardTwice:
    """The pass hears « c'est quoi une pré-production en une phrase ? », the
    slice hears « c'est quoi une pré-production ? » a few seconds later, or
    « préproduction » in one word: one question, one answer."""

    RECENT: ClassVar = [(10.0, own_words("c'est quoi une pré-production en une phrase ?"))]

    def test_the_same_question_short_of_a_word_is_the_same(self):
        assert is_the_same_call("c'est quoi une pré-production ?", self.RECENT, now=15.0)

    def test_a_word_spelt_otherwise_is_the_same(self):
        assert is_the_same_call("c'est quoi une préproduction en une phrase ?", self.RECENT, 15.0)

    def test_a_hyphen_closed_up_and_a_word_short_are_still_the_same(self):
        # Both at once, as the bench heard it: « préproduction ? » after
        # « pré-production en une phrase ? ».
        assert is_the_same_call("c'est quoi une préproduction ?", self.RECENT, 15.0)
        assert own_words("pré-production") == own_words("préproduction")

    def test_another_question_is_another_question(self):
        assert not is_the_same_call("à quel jour est décalée la recette ?", self.RECENT, 15.0)

    def test_thirty_seconds_later_it_is_somebody_asking_again(self):
        assert not is_the_same_call("c'est quoi une pré-production ?", self.RECENT, now=50.0)

    def test_a_question_with_no_word_to_judge_is_never_the_same(self):
        assert not is_the_same_call("et ?", self.RECENT, 15.0)

    def test_thirty_seconds_to_the_second_it_is_still_the_same_question(self):
        assert is_the_same_call("c'est quoi une pré-production ?", self.RECENT,
                                now=10.0 + MEMORY_OF_A_CALL)

    @UNDER_MUTMUT
    @given(asked_at=st.integers(min_value=0, max_value=36_000),
           delay=st.integers(min_value=0, max_value=30))
    def test_only_the_delay_counts_not_the_hour_of_the_meeting(self, asked_at, delay):
        recent = [(float(asked_at), self.RECENT[0][1])]
        assert is_the_same_call("c'est quoi une pré-production ?", recent,
                                now=float(asked_at + delay))

    def test_a_stale_call_before_the_fresh_one_does_not_hide_it(self):
        recent = [(0.0, own_words("à quel jour est décalée la recette ?")), *self.RECENT]
        assert is_the_same_call("c'est quoi une pré-production ?", recent, now=35.0)

    def test_three_words_in_five_are_enough(self):
        asked = own_words("quand livrons recette client final")
        assert is_the_same_call("quand livrons recette bureau mardi", [(10.0, asked)], now=15.0)

    def test_one_word_in_common_is_another_question(self):
        assert not is_the_same_call("c'est quoi la recette ?", self.RECENT, now=15.0)


class TestWhatIsAskedOnceTheNameIsOut:
    """The fallback when nothing follows the name: « Dis-moi Lucie » asks
    « Dis-moi ». The name goes wherever it stands and however it was spelt,
    and what is left still reads as a sentence."""

    def test_the_name_goes_wherever_it_stands(self):
        assert question_asked("Lucie, tu as compris le sujet Lucie ?", "Lucie") == (
            "tu as compris le sujet ?")

    def test_a_name_that_ends_the_sentence_leaves_the_question_before_it(self):
        assert question_asked("Dis-moi Lucie", "Lucie") == "Dis-moi"
        assert question_asked("Tu peux regarder ça Lucie ?", "Lucie") == "Tu peux regarder ça ?"

    def test_a_mangled_name_goes_too(self):
        assert question_asked("Lucy, on décale ?", "Lucie") == "on décale ?"

    def test_a_name_typed_with_a_stray_space_is_still_the_name(self):
        """The settings field keeps what was typed, trailing space included."""
        assert question_asked("Lucy, on décale ?", " Lucie ") == "on décale ?"

    def test_the_comma_the_name_leaves_behind_closes_up(self):
        assert question_asked("Dis-moi Lucie, on décale ?", "Lucie") == "Dis-moi, on décale ?"

    def test_without_the_name_the_sentence_is_the_question(self):
        assert question_asked("on décale ?", "Lucie") == "on décale ?"

    def test_it_agrees_with_the_split_when_the_name_opens_the_sentence(self):
        for text in ("Lucie, à quel jour est décalée la recette ?", "Lucy, on décale ?"):
            assert question_asked(text, "Lucie") == split_at_the_name(text, "Lucie")[1]
