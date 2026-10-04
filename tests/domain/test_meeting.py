"""A kept meeting: who is who, and who is « Les autres »."""

import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from greffier.domain.meeting import (
    IDENTIFIABLE_SECONDS,
    THE_OTHERS,
    Join,
    StoredMeeting,
    held_on,
    named_or_unknown,
    thin_voices,
)
from greffier.domain.models import Span, SpeakerTurn, Utterance

VOICES = ["1", "2", "3", "4", "5", "6"]
#: Seconds of speech: nothing, or at least a thousandth, so that scaling by a
#: power of two stays exact (a subnormal would lose bits).
seconds = st.one_of(st.just(0.0), st.floats(min_value=1e-3, max_value=4000.0))
speaking_times = st.dictionaries(st.sampled_from(VOICES), seconds, min_size=1, max_size=6)
some_names = st.dictionaries(
    st.sampled_from(VOICES), st.sampled_from(["Serge", "Josiane", "Marc"]), max_size=3
)
turns = st.lists(
    st.builds(
        lambda start, length, voice: SpeakerTurn(Span(start, start + length), voice),
        st.floats(min_value=0.0, max_value=3600.0),
        st.floats(min_value=0.0, max_value=600.0),
        st.sampled_from(VOICES),
    ),
    max_size=12,
)
#: Utterances on a grid of whole seconds, each at least one second long: a
#: zero-length utterance is nowhere and would split a hole in two.
grid_utterances = st.lists(
    st.builds(
        lambda start, length, voice: Utterance(Span(start, start + length), "…", voice=voice),
        st.integers(min_value=0, max_value=50),
        st.integers(min_value=1, max_value=10),
        st.sampled_from(VOICES),
    ),
    max_size=8,
)


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


def a_meeting_of_three(**overrides) -> StoredMeeting:
    """Tanguy, Pascal and Sophie, each with a turn and a sentence."""
    defects = dict(
        duration=60.0,
        utterances=[
            Utterance(Span(0, 5), "on cale la recette jeudi", voice="v1"),
            Utterance(Span(6, 11), "le devis part demain", voice="v2"),
            Utterance(Span(11, 14), "et la prod lundi", voice="v2"),
            Utterance(Span(15, 20), "je m'en occupe", voice="v3"),
        ],
        turns=[
            SpeakerTurn(Span(0, 5), "v1"),
            SpeakerTurn(Span(6, 14), "v2"),
            SpeakerTurn(Span(15, 20), "v3"),
        ],
        names={"v1": "Tanguy", "v2": "Pascal", "v3": "Sophie"},
        propositions={"v2": "Pascale"},
    )
    defects.update(overrides)
    return a_meeting(**defects)


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

    def test_three_voices_are_enough_to_switch_the_share_rule_on(self):
        assert thin_voices({}, {"1": 1000.0, "2": 900.0, "3": 20.0}) == {"3"}

    def test_a_voice_of_exactly_six_seconds_is_somebody(self):
        assert thin_voices({}, {"1": 100.0, "2": IDENTIFIABLE_SECONDS}) == set()

    def test_voices_at_the_floor_count_towards_the_three(self):
        """Three scraps of six or seven seconds beside one voice of two hundred:
        they clear the floor, which switches the share rule on, and the share
        rule groups all three. Were the floor exclusive, two of them would be
        announced as people."""
        assert thin_voices({}, {"1": 200.0, "2": 6.0, "3": 6.0, "4": 7.0}) == {"2", "3", "4"}

    def test_a_voice_holding_exactly_a_twentieth_is_not_thin(self):
        # 5 % of 200 s is exactly 10 s in floating point as well.
        assert thin_voices({}, {"1": 100.0, "2": 60.0, "3": 30.0, "4": 10.0}) == set()

    def test_in_a_short_meeting_a_scrap_is_thin_by_the_floor_alone(self):
        """Five seconds and a half out of 105: more than a twentieth, and
        still below what a voiceprint can be trusted on."""
        assert thin_voices({}, {"1": 50.0, "2": 30.0, "3": 20.0, "4": 5.5}) == {"4"}

    @given(names=some_names, speaking=speaking_times, needed=st.integers(min_value=1, max_value=6))
    @example(names={}, speaking={"1": 50.0, "2": 30.0, "3": 20.0, "4": 5.5}, needed=3)
    def test_asking_for_more_voices_never_makes_a_voice_thin(self, names, speaking, needed):
        """The share rule only adds to the floor: switching it off, by asking
        for more voices than there are, cannot turn a scrap into a person."""
        with_the_rule = thin_voices(names, speaking, minimum_voices=needed)
        without = thin_voices(names, speaking, minimum_voices=needed + 1)
        assert without <= with_the_rule

    @given(
        names=some_names, speaking=speaking_times, power=st.integers(min_value=-12, max_value=12)
    )
    @example(
        names={},
        speaking={"1": 1200.0, "2": 1100.0, "3": 900.0, "4": 37.0, "5": 25.0, "6": 4.0},
        power=-12,
    )
    def test_the_rule_is_about_shares_and_the_floor_not_the_unit(self, names, speaking, power):
        """Counted in minutes or in seconds, the same voices are thin. A power
        of two keeps every comparison exact, so this is the rule and not the
        arithmetic that is tested."""
        factor = 2.0**power
        scaled = {voice: duration * factor for voice, duration in speaking.items()}
        assert thin_voices(names, scaled, floor=IDENTIFIABLE_SECONDS * factor) == thin_voices(
            names, speaking
        )

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

    def test_a_voice_of_exactly_ten_seconds_is_an_attendee(self):
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 1000), "1"), SpeakerTurn(Span(1000, 1010), "2")],
        )
        assert meeting.attendees() == ["1", "2"]
        assert meeting.attendees(minimum=11.0) == ["1"]


class TestWhatAVoiceIsCalled:
    def test_no_voice_at_all_is_undetermined(self):
        assert named_or_unknown(None, {}, {}) == "Indéterminé"
        assert a_meeting().name_of(None) == "Indéterminé"

    def test_the_floor_asked_for_is_the_one_used(self):
        """Four seconds are somebody when the floor is lowered to two."""
        speaking = {"1": 100.0, "2": 4.0}
        assert named_or_unknown("2", {}, speaking, floor=2.0) == "Personne 2"
        assert named_or_unknown("2", {}, speaking) == THE_OTHERS

    def test_the_meeting_names_its_voices_from_what_they_carried(self):
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 1200), "1"), SpeakerTurn(Span(1200, 2300), "2"),
                   SpeakerTurn(Span(2300, 3200), "3"), SpeakerTurn(Span(3200, 3237), "4")],
            names={"1": "Serge"},
        )
        assert meeting.name_of("1") == "Serge"
        assert meeting.name_of("2") == "Personne 2"
        assert meeting.name_of("4") == "Les autres"

    def test_the_voices_carrying_a_name_are_found_whatever_the_case(self):
        meeting = a_meeting(names={"v1": "Tanguy", "v2": "tanguy", "v3": "Pascal"})
        assert meeting.voice_named("TANGUY") == ["v1", "v2"]
        assert meeting.voice_named("Pascal") == ["v3"]
        assert meeting.voice_named("Sophie") == []


class TestSpeakingTime:
    @given(turns=turns)
    def test_each_voice_gets_the_sum_of_its_turns(self, turns):
        meeting = a_meeting(turns=turns)
        speaking = meeting.speaking_time()
        assert set(speaking) == {turn.voice for turn in turns}
        for voice, total in speaking.items():
            assert total == pytest.approx(
                sum(turn.span.duration for turn in turns if turn.voice == voice)
            )

    @given(turns=turns)
    @example(turns=[SpeakerTurn(Span(0, 10), "1"), SpeakerTurn(Span(10, 100), "2")])
    def test_the_most_talkative_comes_first(self, turns):
        durations = list(a_meeting(turns=turns).speaking_time().values())
        assert durations == sorted(durations, reverse=True)

    def test_the_spans_of_a_voice_are_its_turns_in_order(self):
        meeting = a_meeting_of_three()
        meeting.turns.append(SpeakerTurn(Span(30, 35), "v1"))
        assert meeting.spans_of("v1") == [Span(0, 5), Span(30, 35)]
        assert meeting.spans_of("v9") == []


class TestWhenTheMeetingWasHeld:
    def test_the_identifier_carries_the_day_and_the_hour(self):
        assert held_on("2026-09-09_10h05_reunion") == (2026, 9, 9, 10, 5)

    def test_without_an_hour_the_day_is_read_at_midnight(self):
        assert held_on("2026-09-09_reunion") == (2026, 9, 9, 0, 0)

    def test_an_identifier_that_does_not_open_with_a_date_has_none(self):
        assert held_on("fausse-reunion") is None
        assert held_on("reunion_2026-09-09") is None

    @given(
        when=st.datetimes(
            min_value=datetime(1000, 1, 1),  # noqa: DTZ001  # st.datetimes takes naive bounds
            max_value=datetime(9999, 12, 31),  # noqa: DTZ001  # st.datetimes takes naive bounds
        ),
        subject=st.text(alphabet="abcdefghijklmnopqrstuvwxyz-", max_size=10),
    )
    def test_the_date_written_in_the_identifier_is_the_date_read_back(self, when, subject):
        with_the_hour = held_on(f"{when:%Y-%m-%d_%Hh%M}_{subject}")
        assert with_the_hour == (when.year, when.month, when.day, when.hour, when.minute)
        assert held_on(f"{when:%Y-%m-%d}_{subject}") == (when.year, when.month, when.day, 0, 0)


class TestJoiningTwoVoices:
    """Naming two voices alike joins them after the meeting as it does live:
    what the tool cut in two becomes one person again."""

    def test_joining_a_voice_into_itself_changes_nothing(self):
        meeting = a_meeting_of_three()
        before = copy.deepcopy(meeting)
        assert meeting.join_into("v2", "v2") == 0
        assert meeting == before

    def test_it_counts_the_turns_that_moved(self):
        # Two sentences but one turn: the turns are what the count is about.
        assert a_meeting_of_three().join_into("v2", "v1") == 1

    def test_every_turn_and_sentence_of_the_absorbed_voice_changes_hands(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        assert [turn.voice for turn in meeting.turns] == ["v1", "v1", "v3"]
        assert [u.voice for u in meeting.utterances] == ["v1", "v1", "v1", "v3"]

    def test_the_absorbed_voice_loses_its_name_and_its_proposition(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        assert meeting.names == {"v1": "Tanguy", "v3": "Sophie"}
        assert meeting.propositions == {}

    def test_what_it_takes_to_undo_is_recorded(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        assert meeting.joins == [
            Join(absorbed="v2", kept="v1", turns=(1,), utterances=(1, 2),
                 name="Pascal", proposition="Pascale"),
        ]

    def test_a_voice_nobody_named_is_recorded_without_a_name(self):
        meeting = a_meeting_of_three(names={}, propositions={})
        meeting.join_into("v3", "v1")
        assert meeting.joins[-1].name is None
        assert meeting.joins[-1].proposition is None

    def test_the_kept_voice_speaks_for_both(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        assert meeting.speaking_time()["v1"] == pytest.approx(13.0)
        assert "v2" not in meeting.speaking_time()


class TestSplittingTwoVoices:
    def test_only_the_voice_that_kept_can_be_split(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        assert meeting.can_split("v1")
        assert not meeting.can_split("v2")
        assert not meeting.can_split("v3")

    def test_nothing_to_undo_returns_nothing_and_breaks_nothing(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        before = copy.deepcopy(meeting)
        assert meeting.split("v3") is None
        assert meeting == before

    def test_the_absorbed_voice_takes_everything_back(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        undone = meeting.split("v1")
        assert undone is not None and undone.absorbed == "v2"
        assert meeting == a_meeting_of_three(processed_at=meeting.processed_at)
        assert not meeting.can_split("v1")

    def test_the_last_join_comes_apart_first(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v2", "v1")
        meeting.join_into("v3", "v1")
        meeting.split("v1")
        assert [turn.voice for turn in meeting.turns] == ["v1", "v1", "v3"]
        meeting.split("v1")
        assert [turn.voice for turn in meeting.turns] == ["v1", "v2", "v3"]

    def test_a_voice_that_came_first_takes_its_first_turn_back(self):
        meeting = a_meeting_of_three()
        meeting.join_into("v1", "v2")
        meeting.split("v2")
        assert meeting.turns[0].voice == "v1"
        assert meeting.utterances[0].voice == "v1"

    def test_a_turn_that_vanished_since_the_join_is_skipped(self):
        """The join is kept on disk with the meeting; a file shortened by hand
        must not make undoing it crash, nor touch a turn that is not there."""
        meeting = a_meeting_of_three()
        meeting.join_into("v3", "v1")
        del meeting.turns[2]
        del meeting.utterances[3]
        assert meeting.split("v1") is not None
        assert [turn.voice for turn in meeting.turns] == ["v1", "v2"]
        assert meeting.names["v3"] == "Sophie"

    @given(
        turns=turns,
        names=some_names,
        propositions=some_names,
        absorbed=st.sampled_from(VOICES),
        kept=st.sampled_from(VOICES),
    )
    @example(turns=[SpeakerTurn(Span(0, 5), "1")], names={}, propositions={},
             absorbed="1", kept="2")
    def test_a_join_undone_leaves_the_meeting_as_it_was(
        self, turns, names, propositions, absorbed, kept
    ):
        utterances = [Utterance(turn.span, "…", voice=turn.voice) for turn in turns]
        meeting = a_meeting(
            turns=turns, utterances=utterances, names=names, propositions=propositions
        )
        before = copy.deepcopy(meeting)
        meeting.join_into(absorbed, kept)
        meeting.split(kept)
        assert meeting == before


class TestTheHolesInTheTranscription:
    def test_with_no_sentence_the_whole_recording_is_a_hole(self):
        assert a_meeting(duration=60.0).gaps() == [Span(0.0, 60.0)]

    def test_a_recording_shorter_than_the_minimum_has_no_hole(self):
        assert a_meeting(duration=3.0).gaps() == []

    def test_five_seconds_is_the_minimum_unless_asked_otherwise(self):
        assert a_meeting(duration=5.0).gaps() == [Span(0.0, 5.0)]
        assert a_meeting(duration=4.9).gaps() == []

    def test_an_empty_transcription_as_long_as_the_minimum_is_one_hole(self):
        """Five seconds nobody transcribed are a hole when a sentence follows
        them; alone, with nothing said in the whole recording, they were not."""
        assert a_meeting(duration=5.0).gaps(minimum=5.0) == [Span(0.0, 5.0)]

    def test_the_holes_are_listed_in_order(self):
        meeting = a_meeting(
            duration=100.0,
            utterances=[
                Utterance(Span(60, 95), "au revoir", voice="2"),
                Utterance(Span(0, 40), "bonjour à tous", voice="1"),
            ],
        )
        assert meeting.gaps(minimum=5.0) == [Span(40.0, 60.0), Span(95.0, 100.0)]
        assert meeting.gaps(minimum=30.0) == []

    def test_a_hole_of_exactly_the_minimum_counts(self):
        meeting = a_meeting(
            duration=20.0,
            utterances=[Utterance(Span(0, 10), "…"), Utterance(Span(15, 20), "…")],
        )
        assert meeting.gaps(minimum=5.0) == [Span(10.0, 15.0)]

    def test_an_overlapping_sentence_does_not_open_a_hole(self):
        meeting = a_meeting(
            duration=30.0,
            utterances=[Utterance(Span(0, 30), "…"), Utterance(Span(10, 20), "…")],
        )
        assert meeting.gaps(minimum=5.0) == []

    @given(
        utterances=grid_utterances,
        slack=st.integers(min_value=0, max_value=20),
        minimum=st.integers(min_value=1, max_value=10),
    )
    def test_the_holes_are_exactly_the_seconds_nobody_covers(self, utterances, slack, minimum):
        """Counted second by second: a hole is a run of uncovered seconds at
        least `minimum` long, and nothing else."""
        duration = max((u.span.end for u in utterances), default=0) + slack
        covered = [
            any(u.span.start <= second < u.span.end for u in utterances)
            for second in range(int(duration))
        ]
        runs, start = [], None
        for second, is_covered in enumerate([*covered, True]):
            if not is_covered and start is None:
                start = second
            elif is_covered and start is not None:
                if second - start >= minimum:
                    runs.append((start, second))
                start = None
        meeting = a_meeting(duration=float(duration), utterances=utterances)
        assert [(gap.start, gap.end) for gap in meeting.gaps(minimum=minimum)] == runs


class TestWhatNamesTheMeeting:
    def test_the_chosen_subject_names_it_else_the_identifier(self):
        assert a_meeting(subject="Point Casa").caption == "Point Casa"
        assert a_meeting().caption == "2026-09-10_14h00_reunion"

    def test_the_coverage_is_the_share_of_the_audio_carrying_text(self):
        meeting = a_meeting(duration=100.0, utterances=[Utterance(Span(0, 75), "…")])
        assert meeting.coverage == pytest.approx(0.75)
        assert a_meeting(duration=0.0).coverage == 0.0
