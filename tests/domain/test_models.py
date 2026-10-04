"""The vocabulary of a meeting, and the two words it refuses to form."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.models import Span, Voiceprint

#: An instant of a recording, in seconds.
instants = st.floats(min_value=0.0, max_value=36_000.0, allow_nan=False)


class TestASpan:
    def test_a_reversed_span_is_refused_and_says_which(self):
        """The two instants come from a model's output: the message has to show
        them, since nobody typed them."""
        with pytest.raises(ValueError, match=r"^intervalle inversé : 5\.0 → 3\.0$"):
            Span(5.0, 3.0)

    def test_a_span_of_no_length_is_one(self):
        """An utterance the engine timestamps on one instant exists all the same."""
        assert Span(2.0, 2.0).duration == 0.0

    @given(instants, instants)
    def test_any_two_instants_in_order_make_a_span_of_their_distance(self, one, other):
        span = Span(min(one, other), max(one, other))
        assert span.duration == pytest.approx(abs(one - other))

    @given(instants, instants)
    def test_the_overlap_is_shared_and_never_negative(self, one, other):
        first = Span(min(one, other), max(one, other))
        second = Span(0.0, one)
        assert first.overlap(second) == second.overlap(first) >= 0.0


class TestAVoiceprint:
    def test_an_empty_voiceprint_is_refused(self):
        """A model that returned nothing has not heard a voice; storing the
        nothing would match everybody."""
        with pytest.raises(ValueError, match=r"^empreinte vide$"):
            Voiceprint(())

    def test_one_coordinate_is_a_voiceprint(self):
        assert Voiceprint((0.5,)).vector == (0.5,)
