"""Ce qu'on garde, et pendant combien de temps."""

import pytest

from greffier.domain.retention import Gesture, Rule


class TestRulesThatCannotHold:
    def test_a_negative_delay_is_refused(self):
        with pytest.raises(ValueError, match="négatif"):
            Rule(compress_after=-1)

    def test_deleting_before_compressing_is_refused(self):
        """Le second geste englobe le premier : l'ordre inverse se contredit."""
        with pytest.raises(ValueError, match="doit venir après"):
            Rule(compress_after=30, erase_after=7)


class TestCompressing:
    def test_before_the_delay_nothing_is_touched(self):
        assert Rule(compress_after=7).decide(3, True, False) is Gesture.NOTHING

    def test_after_the_delay_it_compresses(self):
        assert Rule(compress_after=7).decide(8, True, False) is Gesture.COMPRESS

    def test_audio_already_compressed_is_left_alone(self):
        assert Rule(compress_after=7).decide(30, True, True) is Gesture.NOTHING

    def test_a_delay_of_zero_switches_compression_off(self):
        assert Rule(compress_after=0).decide(999, True, False) is Gesture.NOTHING


class TestDeleting:
    def test_switched_off_by_default(self):
        """Erasing loses the only piece that cannot be made again."""
        assert Rule().erase_after == 0
        assert Rule().decide(9999, True, True) is Gesture.NOTHING

    def test_switched_on_it_deletes_past_the_delay(self):
        rule = Rule(compress_after=7, erase_after=90)
        assert rule.decide(91, True, True) is Gesture.ERASE

    def test_it_wins_over_compression(self):
        rule = Rule(compress_after=7, erase_after=90)
        assert rule.decide(120, True, False) is Gesture.ERASE


class TestAMeetingNotYetTranscribedIsUntouchable:
    """Its audio is all that exists of it."""

    def test_never_compressed(self):
        assert Rule(compress_after=1).decide(365, False, False) is Gesture.NOTHING

    def test_never_deleted(self):
        rule = Rule(compress_after=7, erase_after=30)
        assert rule.decide(365, False, True) is Gesture.NOTHING
