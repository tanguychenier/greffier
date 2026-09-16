"""The live-words bench: the moment it cuts a slice when told to cut on silence."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import measure_live  # noqa: E402


def loud_then_quiet(path: Path, loud_s: float, quiet_s: float) -> Path:
    t = np.arange(int(16000 * loud_s)) / 16000
    loud = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    quiet = np.zeros(int(16000 * quiet_s), dtype="float32")
    sf.write(str(path), np.concatenate([loud, quiet]), 16000, subtype="PCM_16")
    return path


class TestCuttingOnSilence:
    def test_the_slice_waits_for_the_room_to_go_quiet(self, tmp_path):
        audio = loud_then_quiet(tmp_path / "a.wav", loud_s=1.5, quiet_s=2.0)
        cut = measure_live.quiet_moment(audio, 0.5, 3.5)
        assert 1.5 <= cut <= 2.0, "the first quiet window after the tone"

    def test_a_room_that_never_goes_quiet_is_cut_at_the_limit(self, tmp_path):
        audio = loud_then_quiet(tmp_path / "b.wav", loud_s=4.0, quiet_s=0.0)
        assert measure_live.quiet_moment(audio, 0.5, 3.0) == 3.0

    def test_a_room_already_quiet_is_cut_at_once(self, tmp_path):
        audio = loud_then_quiet(tmp_path / "c.wav", loud_s=0.0, quiet_s=3.0)
        assert measure_live.quiet_moment(audio, 1.0, 3.0) == 1.0
