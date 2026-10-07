"""Carrying onto the minutes the names a human gave while the meeting ran.

The defect, measured on the meeting of 11 September: the biggest speaker of the
room was named by hand in the window, on seventy-six sentences, and the minutes
that went out called him *une voix non nommée*, while announcing as a
participant somebody who was not in the room. The name reached the voice bank
and nothing else; the pass that writes the minutes cuts the audio again, into
its own voices, and named them from the bank alone.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.models import Span, SpeakerTurn
from greffier.domain.names import SHARE_TO_CARRY, TWICE_THE_NEXT, NamedSpan, from_live


def turn(start, end, voice):
    return SpeakerTurn(span=Span(start, end), voice=voice)


def named(start, end, name):
    return NamedSpan(name=name, span=Span(start, end))


_DURATIONS = st.floats(min_value=0.01, max_value=3600.0)
_INSTANTS = st.floats(min_value=0.0, max_value=120.0)


def some_spans() -> st.SearchStrategy[Span]:
    """Spans of any length, the empty one included: a diariser does emit them."""
    return st.tuples(_INSTANTS, _INSTANTS).map(lambda pair: Span(min(pair), max(pair)))


class TestTheNameIsCarriedOver:
    def test_a_voice_a_human_named_takes_the_name(self):
        found = from_live([named(0, 100, "Kilian")], [turn(0, 100, "26")])
        assert found == {"26": "Kilian"}

    def test_the_two_cuts_need_not_agree(self):
        """They never do: one is made live, the other afterwards."""
        found = from_live(
            [named(0, 40, "Kilian")],
            [turn(0, 30, "26"), turn(30, 60, "26"), turn(60, 100, "26")],
        )
        assert found == {"26": "Kilian"}

    def test_several_voices_of_one_person_are_all_named(self):
        """The later cut split the same person into 39 voices."""
        found = from_live(
            [named(0, 200, "Kilian")],
            [turn(0, 100, "26"), turn(100, 150, "33"), turn(150, 200, "4")],
        )
        assert found == {"26": "Kilian", "33": "Kilian", "4": "Kilian"}

    @given(_DURATIONS)
    def test_a_voice_spoken_entirely_under_one_name_takes_it_however_short(self, duration):
        """A one-second « oui » named live is as named as a ten-minute speech."""
        found = from_live([named(0, duration, "Kilian")], [turn(0, duration, "26")])
        assert found == {"26": "Kilian"}

    def test_a_voice_that_is_brushed_past_does_not_stop_the_others(self):
        """The first voice is crossed for 5 s of its 100, the second is covered."""
        found = from_live([named(95, 150, "Kilian")], [turn(0, 100, "26"), turn(100, 150, "33")])
        assert found == {"33": "Kilian"}

    def test_a_contested_voice_does_not_stop_the_others_either(self):
        found = from_live(
            [named(0, 50, "Kilian"), named(50, 100, "Cédric"), named(100, 150, "Kilian")],
            [turn(0, 100, "26"), turn(100, 150, "33")],
        )
        assert found == {"33": "Kilian"}


class TestWhatIsNotCarriedOver:
    def test_a_brush_past_names_nothing(self):
        """Speech overlaps at the edges; that is not a name."""
        found = from_live([named(0, 5, "Kilian")], [turn(0, 500, "26")])
        assert found == {}

    def test_a_name_given_while_the_voice_was_silent_names_nothing(self):
        found = from_live([named(0, 10, "Kilian")], [turn(20, 24, "26")])
        assert found == {}

    def test_two_people_crossing_one_voice_name_it_neither(self):
        """A voice both of them cross is a voice cut wrong, and a wrong name is
        worse than none."""
        found = from_live(
            [named(0, 50, "Kilian"), named(50, 100, "Cédric")],
            [turn(0, 100, "26")],
        )
        assert found == {}

    def test_two_people_crossing_a_short_voice_leave_it_unnamed_too(self):
        """1.5 s against 1 s is as contested as 60 s against 40."""
        found = from_live(
            [named(0, 1.5, "Kilian"), named(1.5, 2.5, "Cédric")],
            [turn(0, 2.5, "26")],
        )
        assert found == {}

    def test_a_clear_winner_still_wins(self):
        found = from_live(
            [named(0, 90, "Kilian"), named(90, 100, "Cédric")],
            [turn(0, 100, "26")],
        )
        assert found == {"26": "Kilian"}

    def test_exactly_twice_the_next_name_is_enough(self):
        found = from_live(
            [named(0, 60, "Kilian"), named(60, 60 + 60 / TWICE_THE_NEXT, "Cédric")],
            [turn(0, 100, "26")],
        )
        assert found == {"26": "Kilian"}

    @given(
        total=st.floats(min_value=1.0, max_value=3600.0),
        share=st.floats(min_value=0.21, max_value=0.5),
        ratio=st.one_of(st.floats(min_value=0.0, max_value=0.49),
                        st.floats(min_value=0.51, max_value=1.0)),
    )
    def test_the_winner_needs_twice_the_next_name_whatever_the_scale(self, total, share, ratio):
        """The rule is a ratio: it holds on a two-second voice as on an hour."""
        first = share * total
        second = ratio * first
        found = from_live(
            [named(0, first, "Kilian"), named(first, first + second, "Cédric")],
            [turn(0, total, "26")],
        )
        assert found == ({"26": "Kilian"} if ratio < 0.5 else {})

    @pytest.mark.parametrize(("named_spans", "turns"), [
        ([], [turn(0, 100, "26")]),
        ([named(0, 100, "Kilian")], []),
        ([], []),
    ])
    def test_nothing_to_cross_names_nothing(self, named_spans, turns):
        assert from_live(named_spans, turns) == {}

    def test_the_share_is_what_it_says(self):
        court = SHARE_TO_CARRY * 100 - 1
        assert from_live([named(0, court, "Kilian")], [turn(0, 100, "26")]) == {}
        large = SHARE_TO_CARRY * 100 + 1
        assert from_live([named(0, large, "Kilian")], [turn(0, 100, "26")]) == {
            "26": "Kilian"}

    def test_exactly_the_share_carries_the_name(self):
        exact = SHARE_TO_CARRY * 100
        assert from_live([named(0, exact, "Kilian")], [turn(0, 100, "26")]) == {"26": "Kilian"}

    def test_the_share_is_measured_against_every_turn_of_the_voice(self):
        """15 s named out of 100 s spoken is a brush past, even when the last turn
        alone lasts 50 s."""
        found = from_live([named(0, 15, "Kilian")], [turn(0, 50, "26"), turn(50, 100, "26")])
        assert found == {}


class TestWhatHoldsWhateverTheCuts:
    def test_an_empty_turn_beside_a_name_breaks_nothing(self):
        """Diarisers do emit zero-length turns; one under a name is not named by it."""
        found = from_live([named(0, 10, "Kilian")], [turn(5, 5, "26"), turn(0, 10, "33")])
        assert found == {"33": "Kilian"}

    @given(
        st.lists(st.builds(NamedSpan, name=st.sampled_from(["Kilian", "Cédric"]),
                           span=some_spans()), max_size=5),
        st.lists(st.builds(SpeakerTurn, span=some_spans(),
                           voice=st.sampled_from(["26", "33", "4"])), max_size=6),
    )
    def test_a_voice_is_named_only_from_a_span_it_was_heard_under(self, named_spans, turns):
        """Whatever the two cuts, empty turns included, the result never invents."""
        found = from_live(named_spans, turns)
        for voice, name in found.items():
            assert any(
                one.voice == voice and one.span.overlap(span.span) > 0 and span.name == name
                for one in turns for span in named_spans
            )

