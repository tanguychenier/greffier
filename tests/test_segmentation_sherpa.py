"""Cutting a live slice at the changes of speaker, window by window.

The segmentation model reads ten seconds at once and tells the speakers of
that window apart on its own; past ten seconds the engine joins the windows
with the voiceprint model, which is the slow part. Measured on the processor
under load: 0.14 s for a ten-second window, twelve seconds for the same
audio read as one fifteen-second piece. These tests check the windowing
with an engine double; the real model runs in the integration suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from greffier.adapters import segmentation_sherpa as cutting
from greffier.domain.models import Span


class FakeEngine:
    """Returns one turn per window, labelled with the window's length."""

    sample_rate = 16000

    def __init__(self) -> None:
        self.pieces: list[int] = []

    def process(self, piece):
        self.pieces.append(len(piece))
        seconds = len(piece) / self.sample_rate
        segments = [SimpleNamespace(start=0.0, end=seconds, speaker=0)]
        if seconds >= 10:
            segments.append(SimpleNamespace(start=seconds - 2, end=seconds, speaker=1))
        return SimpleNamespace(sort_by_start_time=lambda: segments)


@pytest.fixture
def segmenter(tmp_path, monkeypatch):
    for name in ("segmentation.onnx", "empreintes.onnx"):
        (tmp_path / name).touch()
    tool = cutting.SherpaSliceSegmenter(
        tmp_path / "segmentation.onnx", tmp_path / "empreintes.onnx"
    )
    engine = FakeEngine()
    monkeypatch.setattr(tool, "_the_engine", lambda: engine)
    return tool, engine


def a_slice(tmp_path, seconds: float, frequency: int = 16000):
    audio = tmp_path / "tranche.wav"
    sf.write(audio, np.zeros(int(seconds * frequency), dtype="float32"), frequency)
    return audio


class TestTheWindows:
    def test_a_slice_of_one_window_is_read_whole(self, tmp_path, segmenter):
        tool, engine = segmenter
        turns = tool.turns(a_slice(tmp_path, 10))
        assert engine.pieces == [160000]
        assert [(t.span, t.voice) for t in turns] == [
            (Span(0, 10), "0:0"), (Span(8, 10), "0:1"),
        ]

    def test_the_windows_are_counted_from_the_end(self, tmp_path, segmenter):
        # Fifteen seconds: five of overlap the thread has already shown, then
        # the fresh ten. The fresh ten must be one window, so the cut falls
        # at five, not at ten.
        tool, engine = segmenter
        turns = tool.turns(a_slice(tmp_path, 15))
        assert engine.pieces == [160000, 80000]
        assert [(t.span, t.voice) for t in turns] == [
            (Span(0, 5), "1:0"), (Span(5, 15), "0:0"), (Span(13, 15), "0:1"),
        ]

    def test_the_labels_of_two_windows_never_collide(self, tmp_path, segmenter):
        tool, _ = segmenter
        turns = tool.turns(a_slice(tmp_path, 20))
        assert {t.voice for t in turns} == {"0:0", "0:1", "1:0", "1:1"}

    def test_a_scrap_of_window_is_not_read(self, tmp_path, segmenter):
        tool, engine = segmenter
        tool.turns(a_slice(tmp_path, 10.5))
        assert engine.pieces == [160000]

    def test_a_missing_file_gives_nothing(self, tmp_path, segmenter):
        tool, _ = segmenter
        assert tool.turns(tmp_path / "absente.wav") == []

    def test_a_file_at_another_rate_gives_nothing(self, tmp_path, segmenter):
        # The thread then attributes the slice as a whole, as it did before.
        tool, engine = segmenter
        assert tool.turns(a_slice(tmp_path, 10, frequency=48000)) == []
        assert engine.pieces == []


class TestTheModels:
    def test_a_missing_model_is_said_at_once(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            cutting.SherpaSliceSegmenter(tmp_path / "rien.onnx", tmp_path / "rien.onnx")

    def test_the_engine_runs_on_the_processor(self):
        # A ten-second window costs 0.14 s there; the card is busy with the words.
        assert cutting.PROCESSOR == "cpu"
