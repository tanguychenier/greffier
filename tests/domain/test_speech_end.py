"""The moment somebody stops talking, from level snapshots."""

from greffier.domain.channels import SpeechEnd


class TestWhenSomebodyStops:
    def test_it_says_so_once_the_room_has_been_quiet_half_a_second(self):
        end = SpeechEnd(quiet_s=0.5)
        assert end.note(1.0, speaking=True) is False
        assert end.note(1.25, speaking=False) is False, "too soon to be an end"
        assert end.note(1.5, speaking=False) is True

    def test_it_says_so_once_per_speech(self):
        end = SpeechEnd(quiet_s=0.5)
        end.note(1.0, speaking=True)
        assert end.note(1.6, speaking=False) is True
        assert end.note(1.9, speaking=False) is False
        assert end.note(2.2, speaking=False) is False

    def test_a_new_speech_gives_a_new_end(self):
        end = SpeechEnd(quiet_s=0.5)
        end.note(1.0, speaking=True)
        assert end.note(1.6, speaking=False) is True
        end.note(3.0, speaking=True)
        assert end.note(3.6, speaking=False) is True

    def test_speech_that_goes_on_pushes_the_end_back(self):
        end = SpeechEnd(quiet_s=0.5)
        end.note(1.0, speaking=True)
        end.note(1.25, speaking=True)
        end.note(1.5, speaking=True)
        assert end.note(1.75, speaking=False) is False
        assert end.note(2.0, speaking=False) is True

    def test_silence_with_nobody_before_is_not_an_end(self):
        end = SpeechEnd()
        assert end.note(0.5, speaking=False) is False
        assert end.note(5.0, speaking=False) is False

    def test_an_end_noticed_late_is_still_an_end(self):
        """Snapshots come when whoever watches has time to look: a pass takes
        seconds, and the end it hid is still the earliest moment to listen.
        """
        end = SpeechEnd(quiet_s=0.5)
        end.note(1.0, speaking=True)
        assert end.note(4.0, speaking=False) is True
        assert end.note(4.25, speaking=False) is False, "once"


class TestWhetherAnyoneSpokeSince:
    def test_with_no_snapshot_at_all_it_cannot_tell_and_says_yes(self):
        assert SpeechEnd().spoken_since(4.0) is True

    def test_a_room_quiet_since_the_moment_says_no(self):
        end = SpeechEnd()
        end.note(1.0, speaking=True)
        end.note(2.0, speaking=False)
        end.note(5.0, speaking=False)
        assert end.spoken_since(3.0) is False

    def test_a_word_after_the_moment_says_yes(self):
        end = SpeechEnd()
        end.note(1.0, speaking=True)
        end.note(4.0, speaking=True)
        assert end.spoken_since(3.0) is True

    def test_a_room_that_never_spoke_but_was_watched_says_no(self):
        end = SpeechEnd()
        end.note(1.0, speaking=False)
        assert end.spoken_since(0.0) is False


class TestWhetherTheRoomWentOnTalking:
    """The other side of the question: doubt must not hold an answer back."""

    def test_with_no_snapshot_at_all_it_says_no(self):
        assert SpeechEnd().resumed_after(4.0) is False

    def test_a_breath_in_the_middle_of_a_question_is_seen_as_such(self):
        end = SpeechEnd()
        end.note(1.0, speaking=True)
        assert end.note(1.6, speaking=False) is True, "the pass is prompted here"
        end.note(2.0, speaking=True)
        assert end.resumed_after(1.6) is True

    def test_a_room_quiet_since_the_end_says_no(self):
        end = SpeechEnd()
        end.note(1.0, speaking=True)
        end.note(1.6, speaking=False)
        end.note(3.0, speaking=False)
        assert end.resumed_after(1.6) is False
