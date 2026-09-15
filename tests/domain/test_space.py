"""How much meeting fits in what is left of the disk."""

from __future__ import annotations

import pytest

from greffier.domain.space import (
    BYTES_PER_SECOND,
    Room,
    Verdict,
    said_during_the_meeting,
    said_in_french,
)


def room_for(minutes: float, channels: int = 1) -> Room:
    return Room(int(minutes * 60 * BYTES_PER_SECOND * channels), channels)


class TestTurningBytesIntoMeeting:
    def test_an_hour_of_one_channel(self) -> None:
        assert Room(BYTES_PER_SECOND * 3600).hours == pytest.approx(1.0)

    def test_two_channels_eat_it_twice_as_fast(self) -> None:
        # A video call records the microphone and the system output side by
        # side, which is two files growing at once.
        assert Room(BYTES_PER_SECOND * 3600, channels=2).minutes == pytest.approx(30)

    def test_a_disk_with_nothing_left_holds_nothing(self) -> None:
        assert Room(0).seconds == 0.0

    def test_a_recording_has_at_least_one_channel(self) -> None:
        with pytest.raises(ValueError, match="voie"):
            Room(1000, channels=0)


class TestTheVerdict:
    def test_plenty_of_room_says_nothing(self) -> None:
        assert room_for(240).verdict is Verdict.ENOUGH
        assert said_in_french(room_for(240)) == ""
        assert said_during_the_meeting(room_for(240)) == ""

    def test_less_than_a_long_meeting_is_tight_and_says_so(self) -> None:
        # The measured meetings run from 32 min to 1 h 42: being warned at
        # « 25 minutes left » is being warned once it is too late.
        tight = room_for(90)
        assert tight.verdict is Verdict.TIGHT
        assert "1 h 30" in said_in_french(tight)

    def test_under_five_minutes_starting_is_losing_the_recording(self) -> None:
        nothing_left = room_for(3)
        assert nothing_left.verdict is Verdict.TOO_LITTLE
        assert "ne se refait pas" in said_in_french(nothing_left)

    def test_the_line_shown_during_a_meeting_is_shorter(self) -> None:
        dit = said_during_the_meeting(room_for(20))
        assert dit.startswith("Plus que")
        assert len(dit) < len(said_in_french(room_for(20)))


class TestSayingItInHoursAndMinutes:
    def test_over_an_hour_it_reads_as_hours(self) -> None:
        assert "1 h 20" in said_during_the_meeting(room_for(80))

    def test_a_round_hour_drops_the_minutes(self) -> None:
        assert "1 h d'enregistrement" in said_during_the_meeting(room_for(60))

    def test_under_an_hour_it_reads_as_minutes(self) -> None:
        assert "12 min" in said_during_the_meeting(room_for(12))
