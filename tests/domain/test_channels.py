"""Who is speaking, judged from the channel.

The case that named it: on a real meeting of 25 August 2026, the voice of
whoever was recording arrived 12 dB under the others'. Averaged with them, it
ended up 18 dB under the mix and the segmentation never saw it. Thirteen
minutes of speech missing from the minutes.
"""

from __future__ import annotations

from greffier.domain.channels import ChannelSettings, local_turns, remove, subtract
from greffier.domain.models import Span

PAS = 0.025  # 25 ms, comme l'adaptateur


def levels(motif: list[tuple[float, float, int]]) -> tuple[list[float], list[float]]:
    """Construit deux suites de niveaux depuis (micro_db, systeme_db, trames)."""
    mic: list[float] = []
    system: list[float] = []
    for m, s, how_many in motif:
        mic += [m] * how_many
        system += [s] * how_many
    return mic, system


class TestAQuietVoiceThatIsStillYours:
    def test_a_voice_12_dB_under_the_others_is_still_seen(self) -> None:
        # The case of 25 August: the mic at -34 dB while the system loopback
        # is at -22. Averaging lost it; the channel finds it again.
        mic, system = levels([(-60, -22, 40), (-34, -50, 80), (-60, -22, 40)])
        turns = local_turns(mic, system, PAS)
        assert len(turns) == 1
        assert turns[0].duration == 80 * PAS

    def test_a_mic_quieter_than_the_loopback_is_not_kept(self) -> None:
        # While the others speak, the mic picks up their echo or some noise.
        mic, system = levels([(-34, -22, 200)])
        assert local_turns(mic, system, PAS) == []

    def test_the_margin_guards_against_the_speakers_coming_back(self) -> None:
        # Listening on loudspeakers: the mic hears them again, a little above
        # the loopback. With no margin everything would pass for local.
        mic, system = levels([(-30, -33, 200)])
        assert local_turns(mic, system, PAS) == []
        # With a margin of zero the same input is kept: it really is the margin
        # that decides, and not some other effect.
        souple = ChannelSettings(margin_db=0.0)
        assert local_turns(mic, system, PAS, souple) != []


class TestBackgroundNoise:
    def test_the_silence_of_a_meeting_is_not_speech(self) -> None:
        # Nobody is speaking: the loopback is silent and the noise of the room
        # dominates. With no floor every silence would become a turn.
        mic, system = levels([(-52, -75, 400)])
        assert local_turns(mic, system, PAS) == []

    def test_the_floor_is_a_setting(self) -> None:
        mic, system = levels([(-52, -75, 400)])
        bas = ChannelSettings(floor_db=-60.0)
        assert local_turns(mic, system, PAS, bas) != []


class TestCuttingIntoTurns:
    def test_the_pauses_inside_a_sentence_do_not_cut_the_turn(self) -> None:
        # 0.5 s of silence inside a sentence: one turn, not two.
        mic, system = levels([
            (-30, -60, 40), (-60, -60, 20), (-30, -60, 40),
        ])
        turns = local_turns(mic, system, PAS)
        assert len(turns) == 1

    def test_a_real_silence_separates_two_turns(self) -> None:
        # 1,5 s : la personne a fini, quelqu'un d'autre a parlé entre-temps.
        mic, system = levels([
            (-30, -60, 40), (-60, -60, 60), (-30, -60, 40),
        ])
        assert len(local_turns(mic, system, PAS)) == 2

    def test_a_lone_yes_is_dropped(self) -> None:
        # 0.5 s: an acknowledgement. Keeping them would make hundreds of turns.
        mic, system = levels([(-60, -60, 40), (-30, -60, 20), (-60, -60, 40)])
        assert local_turns(mic, system, PAS) == []

    def test_a_short_sentence_is_kept(self) -> None:
        mic, system = levels([(-60, -60, 40), (-30, -60, 40), (-60, -60, 40)])
        assert len(local_turns(mic, system, PAS)) == 1


class TestWhatMustNotBreak:
    def test_series_of_different_lengths_do_not_crash(self) -> None:
        mic = [-30.0] * 100
        system = [-60.0] * 40
        turns = local_turns(mic, system, PAS)
        assert turns and turns[0].end <= 40 * PAS

    def test_an_empty_input_gives_no_turn(self) -> None:
        assert local_turns([], [], PAS) == []

    def test_a_step_of_zero_is_refused(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="pas"):
            local_turns([-30.0], [-60.0], 0.0)

    def test_speech_running_to_the_end_is_closed(self) -> None:
        mic, system = levels([(-60, -60, 40), (-30, -60, 60)])
        turns = local_turns(mic, system, PAS)
        assert len(turns) == 1
        assert turns[0].end == 100 * PAS


class TestDroppingTheDuplicates:
    def test_a_remote_turn_covered_by_a_local_one_disappears(self) -> None:
        # The segmentation sees only the system loopback, but a participant
        # speaking at the same time leaves a turn astride. Counting both would
        # make two people where one holds the floor.
        distants = [Span(10.0, 14.0)]
        local_spans = [Span(9.0, 15.0)]
        assert remove(distants, local_spans) == []

    def test_an_independent_remote_turn_is_kept(self) -> None:
        distants = [Span(30.0, 40.0)]
        local_spans = [Span(9.0, 15.0)]
        assert remove(distants, local_spans) == distants

    def test_a_mere_partial_overlap_removes_nothing(self) -> None:
        # A quarter overlapping: both spoke, both are kept.
        distants = [Span(10.0, 20.0)]
        local_spans = [Span(18.0, 22.0)]
        assert remove(distants, local_spans) == distants

    def test_with_no_local_turn_nothing_changes(self) -> None:
        distants = [Span(1.0, 2.0), Span(3.0, 4.0)]
        assert remove(distants, []) == distants


class TestWhoIsSpeaking:
    """What the window shows during the meeting, without asking any model."""

    def test_silence(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-70, -70) is WhoSpeaks.NOBODY

    def test_you_alone(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-30, -70) is WhoSpeaks.YOU

    def test_the_others_alone(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-70, -25) is WhoSpeaks.THE_OTHERS

    def test_a_real_overlap(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-20, -35) is WhoSpeaks.BOTH

    def test_the_mic_hearing_the_speakers_again_is_not_you(self) -> None:
        # Listening on loudspeakers: both channels are alive, but the mic does
        # not dominate. Showing "les deux" would make the window flicker on
        # every sentence the others say.
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-28, -25) is WhoSpeaks.THE_OTHERS


class TestInTheRoomAgainstOnACall:
    """Where the sound comes from identifies somebody on a call, nobody round a table.

    A laptop in the middle of a table has nothing in its system loopback: every
    participant speaks into the same mic. Applying the channel separation anyway
    made them **one single voice**, that of whoever was recording. Measured: three
    speakers reduced to one "moi" label.
    """

    def test_on_a_call_the_local_voice_stands_out(self) -> None:
        # The mic dominates the loopback: it is whoever is recording.
        mic, system = levels([(-30, -60, 60)])
        assert local_turns(mic, system, PAS)

    def test_a_silent_loopback_proves_no_local_speech(self) -> None:
        # Round a table the loopback sits at -240 dB the whole time, so every
        # frame of speech "dominates" it and everything would become local. It
        # is the adapter's job not to call this function in that case, but the
        # computation itself has to stay readable to whoever reads it.
        mic, system = levels([(-25, -240, 80)])
        turns = local_turns(mic, system, PAS)
        assert turns, "le calcul reste juste : c'est son usage qui doit être conditionné"


class TestACallOrATable:
    """Telling a video call from a meeting held round a table.

    The first attempt failed, and it cost a set of minutes: testing whether the
    system loopback is non-zero. On a real table meeting it read -53 dB, sound
    having leaked into it, and concluding "video call" attributed the thirty
    minutes to whoever was recording.

    What decides is relative: on a call the others dominate the mic a good part of
    the time, since they come through the loudspeakers. Measured, 57.7% of the
    frames on an hour-long call, 0.0% on a meeting round a table.
    """

    def test_a_video_call_is_recognised(self) -> None:
        from greffier.domain.channels import over_video

        # The others speak half the time.
        mic, system = levels([(-50, -30, 100), (-30, -60, 100)])
        assert over_video(mic, system)

    def test_a_meeting_round_a_table_is_not_taken_for_a_call(self) -> None:
        from greffier.domain.channels import over_video

        # Everybody goes through the mic; the loopback carries nothing.
        mic, system = levels([(-35, -240, 200)])
        assert not over_video(mic, system)

    def test_a_loopback_that_hisses_without_speech_stays_a_room(
        self,
    ) -> None:
        # The case that failed: a loopback at -53 dB, never dominant.
        from greffier.domain.channels import over_video

        mic, system = levels([(-35, -53, 200)])
        assert not over_video(mic, system)

    def test_one_remote_word_does_not_make_a_call(self) -> None:
        # A notification, a sound played in session: two frames out of two hundred.
        from greffier.domain.channels import over_video

        mic, system = levels([(-35, -240, 198), (-50, -30, 2)])
        assert not over_video(mic, system)

    def test_an_empty_input_concludes_no_call(self) -> None:
        from greffier.domain.channels import over_video

        assert not over_video([], [])


class TestSubtractingSpans:
    """Taking out of a passage what the channel attributes to the person at the mic.

    The measured case: the transcription cuts at sentences, not at speaker
    changes. An extract of 1.5 s carrying 0.6 s of local voice gave a mixed
    voiceprint, and the same person became two participants.
    """

    def test_a_slice_in_the_middle_cuts_in_two(self) -> None:
        remainders = subtract(Span(0, 10), [Span(4, 6)])
        assert remainders == [Span(0, 4), Span(6, 10)]

    def test_a_slice_at_the_head_shortens_the_start(self) -> None:
        assert subtract(Span(13.2, 14.7), [Span(9.5, 13.8)]) == [
            Span(13.8, 14.7)
        ]

    def test_a_fully_covered_passage_leaves_nothing(self) -> None:
        assert subtract(Span(2, 4), [Span(0, 10)]) == []

    def test_a_disjoint_passage_stays_whole(self) -> None:
        assert subtract(Span(0, 3), [Span(5, 8)]) == [Span(0, 3)]

    def test_several_slices_subtract_one_after_another(self) -> None:
        remainders = subtract(Span(0, 12), [Span(2, 4), Span(7, 9)])
        assert remainders == [Span(0, 2), Span(4, 7), Span(9, 12)]

    def test_with_nothing_to_remove_the_span_is_unchanged(self) -> None:
        assert subtract(Span(0, 5), []) == [Span(0, 5)]
