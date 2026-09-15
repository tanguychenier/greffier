"""What an empty list has to say, and what its buttons may do.

Reported in use on the « Voix » tab: an empty table under four active
buttons. The table only said what the eye already saw, and the buttons
suggested there was something to do.
"""

from greffier.domain.emptiness import Missing, may_act, meetings, thread, voices


class TestLesReunions:
    def test_before_the_first_one_it_says_so(self):
        assert meetings(0) is Missing.NO_MEETING_YET

    def test_a_list_with_meetings_says_nothing(self):
        assert meetings(1) is None
        assert meetings(40) is None


class TestLesVoix:
    def test_nothing_chosen_is_not_nothing_to_name(self):
        """Both cases are empty, the two sentences are not the same:
        one asks for a click, the other says the work is done."""
        assert voices(a_meeting_is_chosen=False, how_many=0) is Missing.NO_MEETING_CHOSEN
        assert voices(a_meeting_is_chosen=True, how_many=0) is Missing.NO_VOICE_TO_NAME

    def test_a_meeting_chosen_without_its_voices_yet(self):
        """A meeting chosen but not yet processed: nothing to name either."""
        assert voices(a_meeting_is_chosen=True, how_many=0) is Missing.NO_VOICE_TO_NAME

    def test_voices_to_name_say_nothing(self):
        assert voices(a_meeting_is_chosen=True, how_many=3) is None

    def test_nothing_chosen_wins_over_the_count(self):
        """With no meeting chosen, the number of voices means nothing."""
        assert voices(a_meeting_is_chosen=False, how_many=7) is Missing.NO_MEETING_CHOSEN


class TestLeFil:
    def test_empty_until_somebody_speaks(self):
        assert thread(0) is Missing.NO_THREAD_YET

    def test_a_thread_with_turns_says_nothing(self):
        assert thread(1) is None


class TestCeQueLesBoutonsPeuvent:
    def test_nothing_missing_lets_them_act(self):
        assert may_act(None) is True

    def test_anything_missing_holds_them(self):
        for raison in Missing:
            assert may_act(raison) is False
