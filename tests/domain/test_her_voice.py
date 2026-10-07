"""Telling the assistant's own voice from the room's.

What it says comes back in through the capture of everybody else's sound, and
the separation counts it as a participant. Reported in use: « ça détectait mal
les voix et en rajoutait à chaque fois » -- one of them was Lucie answering.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.her_voice import MARGE_S, PART_MINIMUM, is_hers, voices_of


@dataclass
class Span:
    start: float
    end: float


@dataclass
class Turn:
    voice: str
    span: Span


def _tour(voice: str, start: float, end: float) -> Turn:
    return Turn(voice=voice, span=Span(start, end))


def seconds(low: float = 0.0, high: float = 100.0) -> st.SearchStrategy[float]:
    return st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False)


@st.composite
def an_interval(draw) -> tuple[float, float]:
    start = draw(seconds())
    return (start, start + draw(seconds(0.1, 20.0)))


@st.composite
def a_passage_within_her_margins(draw) -> tuple[float, float, tuple[float, float]]:
    """A passage lying inside one of her intervals, margins included."""
    its_start, its_end = draw(an_interval())
    start = draw(seconds(its_start - MARGE_S, its_end + MARGE_S - 0.01))
    end = draw(seconds(start + 0.01, its_end + MARGE_S))
    return start, end, (its_start, its_end)


class TestOnePassage:
    def test_said_inside_one_of_her_intervals_is_hers(self):
        assert is_hers(10.0, 14.0, [(9.5, 15.0)])

    def test_said_elsewhere_is_not(self):
        assert not is_hers(30.0, 34.0, [(9.5, 15.0)])

    def test_a_sentence_merely_overlapping_her_end_belongs_to_the_room(self):
        """Giving it to her would take a participant's words away."""
        assert not is_hers(14.0, 20.0, [(9.5, 15.0)])

    def test_a_syllable_running_over_is_still_hers(self):
        """Her end is estimated from the length of the text, never measured."""
        assert is_hers(10.0, 15.2, [(10.0, 15.0)])

    def test_an_empty_passage_is_nobody(self):
        assert not is_hers(10.0, 10.0, [(0.0, 100.0)])

    def test_with_no_interval_nothing_is_hers(self):
        assert not is_hers(10.0, 14.0, [])


class TestAWholeVoice:
    def test_a_voice_that_is_her_throughout_is_named(self):
        turns = [_tour("v3", 10.0, 14.0), _tour("v3", 40.0, 44.0)]
        assert voices_of(turns, [(9.5, 15.0), (39.5, 45.0)]) == {"v3"}

    def test_a_participant_who_once_talked_over_her_keeps_their_voice(self):
        """Judged on the whole of a voice: one overlap is not an identity."""
        turns = [_tour("v1", 10.0, 14.0)] + [
            _tour("v1", depart, depart + 10.0) for depart in (20.0, 40.0, 60.0)
        ]
        assert voices_of(turns, [(9.5, 15.0)]) == set()

    def test_the_room_is_left_alone(self):
        turns = [_tour("v1", 0.0, 8.0), _tour("v2", 20.0, 28.0)]
        assert voices_of(turns, [(9.5, 15.0)]) == set()

    def test_no_turns_no_voices(self):
        assert voices_of([], [(0.0, 10.0)]) == set()


class TestTheMargins:
    """Her end is estimated from the length of the text, never measured."""

    def test_the_tail_right_after_her_announced_end_is_hers(self):
        assert is_hers(15.0, 15.0 + MARGE_S, [(10.0, 15.0)])

    def test_the_breath_right_before_her_announced_start_is_hers(self):
        assert is_hers(10.0 - MARGE_S, 10.0, [(10.0, 15.0)])

    @given(a_passage_within_her_margins(), st.floats(min_value=0.05, max_value=0.95))
    def test_a_passage_inside_her_interval_is_hers_whatever_the_share_asked(self, case, part):
        start, end, interval = case
        assert is_hers(start, end, [interval], part)

    def test_a_sentence_exactly_half_hers_belongs_to_the_room(self):
        """Giving it to her would take a participant's words away."""
        # Her interval, margin included, covers the first five seconds of ten.
        assert not is_hers(10.0, 20.0, [(0.0, 15.0 - MARGE_S)])
        assert is_hers(10.0, 20.0, [(0.0, 15.0 - MARGE_S)], part=0.49)


class TestJudgingAVoiceOnItsTime:
    @given(an_interval(), st.lists(an_interval(), max_size=4),
           st.floats(min_value=0.1, max_value=0.9))
    def test_a_voice_with_one_turn_is_hers_exactly_when_that_passage_is(
        self, passage, intervals, part,
    ):
        """The judgement on a voice reduces to the judgement on its only passage."""
        start, end = passage
        expected = {"v1"} if is_hers(start, end, intervals, part) else set()
        assert voices_of([_tour("v1", start, end)], intervals, part) == expected

    @given(st.lists(a_passage_within_her_margins(), min_size=1, max_size=5),
           st.floats(min_value=0.05, max_value=0.95))
    def test_a_voice_that_speaks_only_inside_her_intervals_is_hers_whatever_the_share(
        self, passages, part,
    ):
        turns = [_tour("v1", start, end) for start, end, _ in passages]
        intervals = [interval for _, _, interval in passages]
        assert voices_of(turns, intervals, part) == {"v1"}

    def test_the_share_asked_judges_each_passage_and_not_only_the_voice(self):
        """Six seconds hers out of ten: hers at a half, not at seven tenths."""
        interval = (4.0 + MARGE_S, 10.0 - MARGE_S)
        assert voices_of([_tour("v1", 0.0, 10.0)], [interval]) == {"v1"}
        assert voices_of([_tour("v1", 0.0, 10.0)], [interval], part=0.7) == set()

    def test_a_voice_is_judged_by_the_seconds_it_speaks_not_by_the_clock(self):
        """Six seconds of her early on outweigh four seconds of somebody else late."""
        turns = [_tour("v1", 0.0, 6.0), _tour("v1", 100.0, 104.0)]
        assert voices_of(turns, [(0.0, 6.0)]) == {"v1"}

    def test_short_turns_count_like_long_ones(self):
        turns = [_tour("v2", 10.0, 10.8), _tour("v2", 12.0, 12.6)]
        assert voices_of(turns, [(9.5, 13.0)]) == {"v2"}

    def test_a_voice_exactly_half_hers_stays_in_the_room(self):
        turns = [_tour("v1", 10.0, 14.0), _tour("v1", 20.0, 24.0)]
        assert voices_of(turns, [(9.5, 15.0)]) == set()

    def test_the_share_asked_is_the_one_applied(self):
        """Three seconds hers out of four: enough at a half, not at eight tenths."""
        turns = [_tour("v1", 10.0, 13.0), _tour("v1", 20.0, 21.0)]
        assert voices_of(turns, [(9.5, 15.0)], part=PART_MINIMUM) == {"v1"}
        assert voices_of(turns, [(9.5, 15.0)], part=0.8) == set()

    def test_an_empty_turn_hides_nothing_that_follows(self):
        turns = [_tour("v3", 10.0, 10.0), _tour("v3", 10.0, 14.0)]
        assert voices_of(turns, [(9.5, 15.0)]) == {"v3"}

    def test_a_voice_made_only_of_empty_turns_is_not_judged(self):
        assert voices_of([_tour("v1", 10.0, 10.0)], [(0.0, 100.0)]) == set()
