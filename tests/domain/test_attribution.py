"""A sentence astride two speakers must name nobody."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.attribution import MINIMUM_SHARE, time_per_voice, voice_of
from greffier.domain.models import Span, SpeakerTurn


def turn(voice: str, start: float, end: float) -> SpeakerTurn:
    return SpeakerTurn(span=Span(start, end), voice=voice)


def seconds(low: float = 0.0, high: float = 100.0) -> st.SearchStrategy[float]:
    return st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False)


@st.composite
def a_span(draw) -> Span:
    start = draw(seconds())
    return Span(start, start + draw(seconds(0.0, 30.0)))


@st.composite
def some_turns(draw) -> list[SpeakerTurn]:
    turns = []
    for _ in range(draw(st.integers(min_value=0, max_value=8))):
        start = draw(seconds())
        turns.append(turn(draw(st.sampled_from(["0", "1", "2"])), start,
                          start + draw(seconds(0.0, 10.0))))
    return turns


@st.composite
def abutting_turns(draw) -> list[SpeakerTurn]:
    """What the segmenter hands over: one voice at a time, no gap between two."""
    cuts = sorted(draw(st.lists(seconds(), min_size=2, max_size=9, unique=True)))
    voices = draw(st.lists(st.sampled_from(["0", "1", "2"]),
                           min_size=len(cuts) - 1, max_size=len(cuts) - 1))
    return [turn(voice, start, end)
            for voice, start, end in zip(voices, cuts[:-1], cuts[1:], strict=True)]


class TestWhoseVoice:
    def test_a_sentence_inside_one_turn_goes_to_that_voice(self):
        turns = [turn("0", 0.0, 8.0), turn("1", 8.4, 17.0)]
        assert voice_of(Span(0.0, 7.7), turns) == "0"

    def test_a_sentence_in_no_turn_names_nobody(self):
        assert voice_of(Span(0.0, 5.0), []) is None
        assert voice_of(Span(30.0, 35.0), [turn("0", 0.0, 8.0)]) is None

    def test_a_few_hundredths_of_overrun_change_nothing(self):
        """The bounds of the two cuts never coincide exactly.

        Measured: the last utterance of the table meeting held 0.98, an overlap of 0.2 s
        onto the neighbouring turn. Refusing to decide there would leave half the
        sentences with no voice.
        """
        turns = [turn("1", 41.9, 50.4), turn("0", 35.0, 41.2)]
        assert voice_of(Span(41.0, 50.4), turns) == "1"

    def test_a_sentence_astride_a_speaker_change_names_nobody(self):
        """The measured case: "Merci Pierre…", said by Jacques, given to Pierre.

        The transcribed sentence covers 9.6 s of Pierre's turn and 6.1 s of Jacques's,
        which is 0.61 for the leader. The old most-talkative rule gave the whole
        sentence to Pierre.
        """
        turns = [turn("pierre", 24.55, 34.14), turn("jacques", 34.96, 41.07)]
        assert voice_of(Span(23.77, 41.07), turns) is None

    def test_an_even_split_names_nobody(self):
        turns = [turn("0", 0.0, 5.0), turn("1", 5.0, 10.0)]
        assert voice_of(Span(0.0, 10.0), turns) is None

    def test_the_threshold_is_met_at_the_minimum_share(self):
        """Exactly at the threshold it decides: the refusal starts below."""
        turns = [turn("0", 0.0, 8.0), turn("1", 8.0, 10.0)]
        assert voice_of(Span(0.0, 10.0), turns, MINIMUM_SHARE) == "0"
        assert voice_of(Span(0.0, 10.0), turns, 0.81) is None

    def test_the_scattered_pieces_of_one_voice_add_up(self):
        """A voice cut in two by an interjection is still the same voice."""
        turns = [turn("0", 0.0, 4.0), turn("1", 4.0, 4.5), turn("0", 4.5, 10.0)]
        assert voice_of(Span(0.0, 10.0), turns) == "0"

    def test_a_sentence_under_a_second_long_still_has_a_voice(self):
        """« Oui. » lasts half a second and is somebody's."""
        assert voice_of(Span(3.0, 3.5), [turn("0", 0.0, 8.0)]) == "0"


class TestSpeakingTimePerVoice:
    def test_each_voice_gets_its_overlapping_time(self):
        turns = [turn("0", 0.0, 4.0), turn("1", 4.0, 10.0)]
        assert time_per_voice(Span(2.0, 6.0), turns) == {"0": 2.0, "1": 2.0}

    def test_a_turn_outside_the_sentence_does_not_count(self):
        assert time_per_voice(Span(0.0, 3.0), [turn("0", 5.0, 9.0)]) == {}

    def test_a_fraction_of_a_second_counts(self):
        assert time_per_voice(Span(0.0, 0.6), [turn("0", 0.0, 10.0)]) == {"0": 0.6}

    def test_the_pieces_of_one_voice_are_added_up(self):
        turns = [turn("0", 0.0, 2.0), turn("1", 2.0, 3.0), turn("0", 3.0, 10.0)]
        assert time_per_voice(Span(0.0, 6.0), turns) == {"0": 5.0, "1": 1.0}

    @given(a_span(), abutting_turns())
    def test_the_voices_together_hold_exactly_the_time_the_sentence_spends_in_the_turns(
        self, span, turns,
    ):
        """Nothing is counted twice and nothing is lost between two turns."""
        held = time_per_voice(span, turns)
        covered = Span(turns[0].span.start, turns[-1].span.end)
        assert sum(held.values()) == pytest.approx(span.overlap(covered))
        assert all(seconds_held > 0 for seconds_held in held.values())

    @given(a_span(), some_turns(), st.floats(min_value=0.0, max_value=1.0))
    def test_cutting_every_turn_in_two_changes_what_no_voice_holds(self, span, turns, where):
        """A voice holds the sum of its pieces, however the segmenter cut them."""
        pieces = []
        for one in turns:
            cut = min(one.span.end, one.span.start + where * one.span.duration)
            pieces += [turn(one.voice, one.span.start, cut), turn(one.voice, cut, one.span.end)]
        assert time_per_voice(span, pieces) == pytest.approx(time_per_voice(span, turns))
