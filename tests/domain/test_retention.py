"""What is kept, and for how long."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.retention import Gesture, Rule

#: A delay in days, as the settings file states it.
delays = st.integers(min_value=1, max_value=3650)


class TestRulesThatCannotHold:
    @pytest.mark.parametrize("delay", ["compress_after", "erase_after"])
    def test_a_negative_delay_is_refused(self, delay):
        with pytest.raises(
            ValueError, match=r"^un délai de rétention ne peut pas être négatif$",
        ):
            Rule(**{delay: -1})

    def test_deleting_before_compressing_is_refused(self):
        """The second gesture includes the first: the other order contradicts itself."""
        with pytest.raises(ValueError, match=(
            r"^« effacer_apres » doit venir après « compresser_apres », "
            r"sinon l'audio disparaît avant d'avoir été compressé$"
        )):
            Rule(compress_after=30, erase_after=7)

    def test_deleting_the_day_it_is_compressed_is_allowed(self):
        """Compressed in the morning and erased in the evening is one gesture, not
        a contradiction: « après » is read as « pas avant »."""
        assert Rule(compress_after=7, erase_after=7).erase_after == 7

    @given(delays, delays)
    def test_the_refusal_stops_on_the_day_of_the_compression(self, erase_after, shorter):
        """Whatever the two delays, an erasure set strictly before the compression
        is refused with its sentence; moved up to the day of the compression, the
        same rule holds. The frontier is the day itself, on both sides."""
        compress_after = erase_after + shorter
        with pytest.raises(ValueError, match=(
            r"^« effacer_apres » doit venir après « compresser_apres », "
            r"sinon l'audio disparaît avant d'avoir été compressé$"
        )):
            Rule(compress_after=compress_after, erase_after=erase_after)
        held = Rule(compress_after=compress_after, erase_after=compress_after)
        assert held.erase_after == compress_after


class TestCompressing:
    def test_before_the_delay_nothing_is_touched(self):
        assert Rule(compress_after=7).decide(3, True, False) is Gesture.NOTHING

    def test_after_the_delay_it_compresses(self):
        assert Rule(compress_after=7).decide(8, True, False) is Gesture.COMPRESS

    def test_on_the_day_itself_it_compresses(self):
        """« After seven days » is on the seventh, not on the eighth."""
        assert Rule(compress_after=7).decide(7, True, False) is Gesture.COMPRESS

    @given(delays, st.floats(min_value=0, max_value=3650, allow_nan=False))
    def test_from_the_delay_on_an_uncompressed_meeting_is_compressed(self, delay, extra):
        assert Rule(compress_after=delay).decide(delay + extra, True, False) is Gesture.COMPRESS

    @given(delays, st.floats(min_value=0, max_value=1, exclude_max=True))
    def test_before_the_delay_nothing_is_touched_whatever_the_age(self, delay, share):
        assert Rule(compress_after=delay).decide(delay * share, True, False) is Gesture.NOTHING

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

    def test_on_the_day_itself_it_deletes(self):
        rule = Rule(compress_after=7, erase_after=90)
        assert rule.decide(90, True, True) is Gesture.ERASE

    @given(delays, delays, st.floats(min_value=0, max_value=3650, allow_nan=False),
           st.booleans())
    def test_from_the_delay_on_a_transcribed_meeting_is_erased_compressed_or_not(
        self, compress_after, erase_after, extra, already_compressed,
    ):
        rule = Rule(compress_after=compress_after,
                    erase_after=max(compress_after, erase_after))
        assert rule.decide(
            rule.erase_after + extra, True, already_compressed,
        ) is Gesture.ERASE

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
