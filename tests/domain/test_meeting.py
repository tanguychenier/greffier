"""A kept meeting: who is who, and who is « Les autres »."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span, SpeakerTurn, Utterance


def a_meeting(**overrides) -> StoredMeeting:
    defects = dict(
        identifier="2026-09-10_14h00_reunion",
        audio=Path("/enregistrements/r.wav"),
        processed_at=datetime.now(UTC),
        duration=3878.0,
        utterances=[],
        turns=[],
        names={},
        propositions={},
        warnings=[],
    )
    defects.update(overrides)
    return StoredMeeting(**defects)


class TestTheThinVoicesAreTheOthers:
    """The meeting of 2026-09-10, six people: the chain announced twelve
    voices, six of them holding 4 to 37 seconds of the 3 878. Grouped under
    « Les autres », they are no longer announced as people."""

    def _speaking(self):
        return {"1": 1200.0, "2": 1100.0, "3": 900.0, "4": 37.0, "5": 25.0, "6": 4.0}

    def test_an_unnamed_voice_under_a_twentieth_of_the_time_is_thin(self):
        from greffier.domain.meeting import thin_voices

        assert thin_voices({}, self._speaking()) == {"4", "5", "6"}

    def test_a_named_voice_is_never_thin(self):
        from greffier.domain.meeting import thin_voices

        assert thin_voices({"4": "Serge"}, self._speaking()) == {"5", "6"}

    def test_with_fewer_than_three_voices_only_the_scraps_are_thin(self):
        """Two people, one of them quiet: the quiet one is still a person."""
        from greffier.domain.meeting import thin_voices

        assert thin_voices({}, {"1": 1000.0, "2": 30.0, "3": 4.0}) == {"3"}

    def test_the_thin_voices_are_called_the_others(self):
        from greffier.domain.meeting import named_or_unknown

        speaking = self._speaking()
        assert named_or_unknown("4", {}, speaking) == "Les autres"
        assert named_or_unknown("1", {}, speaking) == "Personne 1"
        assert named_or_unknown("4", {"4": "Serge"}, speaking) == "Serge"

    def test_the_attendees_leave_the_others_out(self):
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 1200), "1"), SpeakerTurn(Span(1200, 2300), "2"),
                   SpeakerTurn(Span(2300, 3200), "3"), SpeakerTurn(Span(3200, 3237), "4")],
            names={},
        )
        assert meeting.attendees() == ["1", "2", "3"]


class TestTheHolesInTheTranscription:
    def test_a_hole_of_exactly_the_minimum_counts(self):
        meeting = a_meeting(
            duration=20.0,
            utterances=[Utterance(Span(0, 10), "…"), Utterance(Span(15, 20), "…")],
        )
        assert meeting.gaps(minimum=5.0) == [Span(10.0, 15.0)]

    def test_an_empty_transcription_as_long_as_the_minimum_is_one_hole(self):
        """Five seconds nobody transcribed are a hole when a sentence follows
        them; alone, with nothing said in the whole recording, they were not."""
        assert a_meeting(duration=5.0).gaps(minimum=5.0) == [Span(0.0, 5.0)]
