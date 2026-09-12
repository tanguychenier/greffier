"""Carrying onto the minutes the names a human gave while the meeting ran.

The defect, measured on the meeting of 11 September: the biggest speaker of the
room was named by hand in the window, on seventy-six sentences, and the minutes
that went out called him *une voix non nommée*, while announcing as a
participant somebody who was not in the room. The name reached the voice bank
and nothing else; the pass that writes the minutes cuts the audio again, into
its own voices, and named them from the bank alone.
"""

import pytest

from greffier.domain.models import Span, SpeakerTurn
from greffier.domain.names import SHARE_TO_CARRY, NamedSpan, from_live


def turn(start, end, voice):
    return SpeakerTurn(span=Span(start, end), voice=voice)


def named(start, end, name):
    return NamedSpan(name=name, span=Span(start, end))


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


class TestWhatIsNotCarriedOver:
    def test_a_brush_past_names_nothing(self):
        """Speech overlaps at the edges; that is not a name."""
        found = from_live([named(0, 5, "Kilian")], [turn(0, 500, "26")])
        assert found == {}

    def test_two_people_crossing_one_voice_name_it_neither(self):
        """A voice both of them cross is a voice cut wrong, and a wrong name is
        worse than none."""
        found = from_live(
            [named(0, 50, "Kilian"), named(50, 100, "Cédric")],
            [turn(0, 100, "26")],
        )
        assert found == {}

    def test_a_clear_winner_still_wins(self):
        found = from_live(
            [named(0, 90, "Kilian"), named(90, 100, "Cédric")],
            [turn(0, 100, "26")],
        )
        assert found == {"26": "Kilian"}

    @pytest.mark.parametrize("named_spans,turns", [
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
