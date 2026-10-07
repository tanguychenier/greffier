"""When a spoken sentence is over.

Holding a button down says it, and makes the person hold a mouse while they read
the document they are asking about -- which is what they are doing when they
prepare a meeting. So silence ends the take.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.dictating import SILENCE_DB, Take

#: One reading of the meter: a level in dB and the time since the last one.
readings = st.tuples(
    st.floats(min_value=-90.0, max_value=0.0, allow_nan=False),
    st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
)


def _speaks(take: Take, total_seconds: float, pas: float = 0.2) -> None:
    for _ in range(int(total_seconds / pas)):
        take.heard(-20.0, pas)


def _goes_quiet(take: Take, total_seconds: float, pas: float = 0.2) -> None:
    for _ in range(int(total_seconds / pas)):
        take.heard(-60.0, pas)


class TestWhenItEnds:
    def test_speech_then_silence_ends_it(self):
        take = Take()
        _speaks(take, 2.0)
        assert not take.over
        _goes_quiet(take, 1.6)
        assert take.over

    def test_a_pause_inside_a_sentence_does_not(self):
        """French carries pauses of nearly a second between two words."""
        take = Take()
        _speaks(take, 2.0)
        _goes_quiet(take, 0.8)
        assert not take.over
        _speaks(take, 1.0)
        assert not take.over

    def test_somebody_who_says_nothing_is_not_finished(self):
        """They are thinking, or the microphone is the wrong one."""
        take = Take()
        _goes_quiet(take, 10.0)
        assert not take.over

    def test_a_first_word_cut_by_its_own_breath_is_not_the_end(self):
        take = Take()
        _speaks(take, 0.4)
        _goes_quiet(take, 2.0)
        assert not take.over, "moins d'une seconde de prise : rien à transcrire"

    def test_a_reading_exactly_at_the_floor_is_silence(self):
        """The floor is the loudest a room may be, so a room at the floor is
        still a room: it does not interrupt the quiet that ends the take."""
        take = Take()
        _speaks(take, 2.0)
        for _ in range(8):
            take.heard(SILENCE_DB, 0.2)
        assert take.over
        assert take.talked == pytest.approx(2.0)

    def test_the_floor_is_below_speech_and_above_a_room(self):
        """Measured on the meters: speech -30 to -12, a quiet room -60 to -50."""
        assert -50 < SILENCE_DB < -30


class TestHowLongTheTakeHasLasted:
    """The ceiling on a recording is set on this clock, speech or silence."""

    def test_speech_and_silence_both_count(self):
        take = Take()
        _speaks(take, 2.0)
        _goes_quiet(take, 1.6)
        assert take.elapsed == pytest.approx(3.6)

    @given(st.lists(readings))
    def test_the_time_elapsed_is_the_sum_of_the_readings_whatever_their_level(
        self, heard,
    ):
        take = Take()
        for level_db, since in heard:
            take.heard(level_db, since)
        assert take.elapsed == pytest.approx(sum(since for _, since in heard))
