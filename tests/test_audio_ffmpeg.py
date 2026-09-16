"""The recorder's gestures that run ffmpeg, on real and tiny files.

Stitching chunks, levelling a take, reading its levels, stopping the encoder
without killing it: each was covered by nothing but the meetings themselves.
Skipped where ffmpeg is not installed.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from greffier.adapters.audio_ffmpeg import DIGITAL_SILENCE, FfmpegRecorder

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


def tone(path: Path, seconds: float = 0.5, channels: int = 1, level: float = 0.3) -> Path:
    """A 440 Hz tone, or silence when the level is nought."""
    t = np.arange(int(16000 * seconds)) / 16000
    signal_ = (level * np.sin(2 * np.pi * 440 * t)).astype("float32")
    frames = np.stack([signal_] * channels, axis=1) if channels > 1 else signal_
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), frames, 16000, subtype="PCM_16")
    return path


class TestStitchingTheChunks:
    def test_two_chunks_become_one_recording_of_their_length(self, tmp_path):
        first, second = tone(tmp_path / "a-01.wav", 0.5), tone(tmp_path / "a-02.wav", 0.7)
        whole = FfmpegRecorder("default", 60).wire_up([first, second], tmp_path / "a.wav")
        assert abs(sf.info(str(whole)).duration - 1.2) < 0.02

    def test_a_single_chunk_is_moved_not_copied(self, tmp_path):
        only = tone(tmp_path / "a-01.wav")
        whole = FfmpegRecorder("default", 60).wire_up([only], tmp_path / "a.wav")
        assert whole == tmp_path / "a.wav" and whole.exists()
        assert not only.exists()

    def test_chunks_with_different_channel_counts_are_brought_to_the_fewest(self, tmp_path):
        mono, stereo = tone(tmp_path / "a-01.wav", 0.5, 1), tone(tmp_path / "a-02.wav", 0.5, 2)
        whole = FfmpegRecorder("default", 60).wire_up([mono, stereo], tmp_path / "a.wav")
        assert sf.info(str(whole)).channels == 1
        assert abs(sf.info(str(whole)).duration - 1.0) < 0.02

    def test_an_empty_chunk_is_left_out(self, tmp_path):
        first = tone(tmp_path / "a-01.wav", 0.5)
        empty = tmp_path / "a-02.wav"
        empty.write_bytes(b"")
        whole = FfmpegRecorder("default", 60).wire_up([first, empty], tmp_path / "a.wav")
        assert abs(sf.info(str(whole)).duration - 0.5) < 0.02

    def test_with_nothing_usable_it_says_so(self, tmp_path):
        with pytest.raises(RuntimeError, match="aucun morceau exploitable"):
            FfmpegRecorder("default", 60).wire_up([tmp_path / "absent.wav"], tmp_path / "a.wav")


class TestLevellingATake:
    def test_a_quiet_mono_take_comes_out_louder_and_mono(self, tmp_path):
        quiet = tone(tmp_path / "quiet.wav", 1.0, 1, level=0.02)
        levelled = FfmpegRecorder("default", 60).prepare_transcript(quiet, tmp_path / "out.wav")
        assert levelled == tmp_path / "out.wav"
        before, after = sf.read(str(quiet))[0], sf.read(str(levelled))[0]
        assert np.abs(after).max() > np.abs(before).max() * 3

    def test_a_stereo_take_is_mixed_to_one_channel(self, tmp_path):
        stereo = tone(tmp_path / "stereo.wav", 1.0, 2)
        levelled = FfmpegRecorder("default", 60).prepare_transcript(stereo, tmp_path / "out.wav")
        assert sf.info(str(levelled)).channels == 1

    def test_a_file_ffmpeg_cannot_read_is_handed_back_as_it_is(self, tmp_path):
        broken = tmp_path / "broken.wav"
        broken.write_bytes(b"RIFF" + b"\0" * 40)
        assert FfmpegRecorder("default", 60).prepare_transcript(
            broken, tmp_path / "out.wav"
        ) == broken


class TestReadingTheLevels:
    def test_a_tone_and_silence_are_told_apart_per_channel(self, tmp_path):
        loud = tone(tmp_path / "loud.wav", 0.5, 1, level=0.3)
        assert FfmpegRecorder("default", 60).levels(loud)[0] > -20
        quiet = tone(tmp_path / "quiet.wav", 0.5, 1, level=0.0)
        assert FfmpegRecorder("default", 60).levels(quiet) == [DIGITAL_SILENCE]

    def test_off_macos_trying_a_device_listens_to_nothing(self, monkeypatch):
        monkeypatch.setattr("greffier.adapters.audio_ffmpeg.SYSTEM", "Linux")
        assert FfmpegRecorder("default", 60).try_it("micro") == 0.0


class TestStoppingTheEncoder:
    """SIGINT, never SIGKILL: a wav killed has no header, and no header is
    an unreadable meeting."""

    def test_a_process_that_leaves_on_sigint_is_not_killed(self):
        script = ("import signal, sys, time\n"
                  "signal.signal(signal.SIGINT, lambda *a: sys.exit(0))\ntime.sleep(30)\n")
        child = subprocess.Popen([sys.executable, "-c", script])
        try:
            import time

            time.sleep(0.3)
            FfmpegRecorder("default", 60).stop_recording(child.pid)
            assert child.wait(timeout=5) == 0, "left on SIGINT, exit code 0"
        finally:
            if child.poll() is None:
                child.kill()

    def test_a_process_already_gone_costs_nothing(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        FfmpegRecorder("default", 60).stop_recording(child.pid)

    def test_a_process_that_ignores_sigint_is_killed_in_the_end(self, monkeypatch):
        script = ("import signal, time\n"
                  "signal.signal(signal.SIGINT, signal.SIG_IGN)\ntime.sleep(60)\n")
        child = subprocess.Popen([sys.executable, "-c", script])
        try:
            import time

            time.sleep(0.3)
            monkeypatch.setattr(time, "sleep", lambda s: None)
            FfmpegRecorder("default", 60).stop_recording(child.pid)
            assert child.wait(timeout=5) == -signal.SIGKILL
        finally:
            if child.poll() is None:
                child.kill()
