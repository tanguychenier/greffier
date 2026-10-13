"""What the channels of a recording say about where the sound came from.

These cases used to live in the device tests, and had to force a diariser
instance without initialising it to reach a private method. Now that the rule
has a module of its own they are written directly, and the live thread leans on
the same code as the final processing, which is the point: the window must not
show a speaker the minutes will contradict.
"""

from __future__ import annotations

import numpy as np

from greffier.adapters.channels_file import (
    FileChannelReader,
    levels_per_frame,
    split_channels,
)


def signal(channels: list[list[float]]) -> np.ndarray:
    return np.array(channels, dtype="float32").T


class TestVisioOuPresentiel:
    def test_a_loopback_that_dominates_means_a_call(self) -> None:
        # The others come through the loudspeakers and cover the mic: that is
        # what marks a video call, not the mere presence of a signal.
        fort, weak = [0.2] * 16000, [0.001] * 16000
        channels = split_channels(signal([weak, fort, fort]))
        assert channels.remote
        assert channels.mic is not None

    def test_a_loopback_alive_but_never_dominant_stays_a_room(self) -> None:
        # The case that had failed: a loopback at -53 dB, sound having leaked
        # into it, but never covering the mic. Concluding "video call"
        # attributed thirty minutes of meeting to the one person recording.
        channels = split_channels(signal([[0.2] * 16000, [0.002] * 16000, [0.002] * 16000]))
        assert not channels.remote
        # And the mic is what has to be segmented, where everybody speaks.
        assert float(abs(channels.system).max()) > 0.1

    def test_a_silent_loopback_means_in_the_room(self) -> None:
        # The laptop set in the middle of a table.
        channels = split_channels(signal([[0.1] * 16000, [0.0] * 16000, [0.0] * 16000]))
        assert not channels.remote
        assert float(abs(channels.system).max()) > 0

    def test_a_silent_channel_does_not_divide_the_others_amplitude(self) -> None:
        channels = split_channels(signal([[0.001] * 16000, [0.0] * 16000, [0.2] * 16000]))
        assert channels.remote
        assert float(abs(channels.system).max()) > 0.15

    def test_a_mono_file_allows_no_separation(self) -> None:
        channels = split_channels(signal([[0.1] * 100]))
        assert channels.mic is None and not channels.remote


class TestAVideoCallStaysAVideoCall:
    """The verdict is read over the whole audio, not over ten seconds.

    The measured defect: on a slice where only the person at the mic speaks, no
    loopback dominates, so "in a room", and their voice, no longer named by the
    channel, became one more remote participant.
    """

    def test_the_forced_mode_wins_over_what_the_slice_says(self) -> None:
        only_my_voice = signal([[0.2] * 16000, [0.0] * 16000, [0.0] * 16000])
        assert not split_channels(only_my_voice).remote
        assert split_channels(only_my_voice, remote=True).remote

    def test_a_silent_loopback_forced_to_a_call_leaves_the_floor_to_the_mic(self) -> None:
        # This is what keeps "Toi" on screen when nobody else speaks for a
        # whole slice.
        channels = split_channels(
            signal([[0.2] * 16000, [0.0] * 16000, [0.0] * 16000]), remote=True
        )
        assert channels.mic is not None
        assert float(abs(channels.system).max()) == 0.0

    def test_the_reader_keeps_the_verdict_from_one_slice_to_the_next(
        self, tmp_path
    ) -> None:
        import soundfile as sf

        player = FileChannelReader()
        assert not player.remote
        # A slice of a video call: the loopback covers the mic.
        visio = tmp_path / "visio.wav"
        sf.write(visio, signal([[0.001] * 16000, [0.2] * 16000, [0.2] * 16000]), 16000)
        player.local_passages(visio)
        assert player.remote
        # The next slice carries only my voice: the verdict holds, and this
        # passage is attributed to me instead of creating a remote voice.
        alone = tmp_path / "seul.wav"
        sf.write(alone, signal([[0.2] * 32000, [0.0] * 32000, [0.0] * 32000]), 16000)
        assert player.local_passages(alone) != []


class TestLevels:
    def test_digital_silence_does_not_give_minus_infinity(self) -> None:
        levels = levels_per_frame(np.zeros(16000, dtype="float32"), 16000)
        assert levels and all(n < -200 for n in levels)

    def test_a_signal_too_short_for_a_frame_gives_nothing(self) -> None:
        assert levels_per_frame(np.zeros(10, dtype="float32"), 16000) == []


class TestReadingTheSetting:
    def test_an_unreadable_file_does_not_stop_the_meeting(self, tmp_path) -> None:
        # A slice cut while the file is being written may arrive truncated:
        # the live thread then shows the sentence without « Toi », it does not stop.
        absent = tmp_path / "rien.wav"
        assert FileChannelReader().local_passages(absent) == []
