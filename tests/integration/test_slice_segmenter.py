"""The segmentation model on a live slice, the way the follower calls it.

A ten-second slice where two people talk used to go whole to one voice;
the slice is now cut at the changes of speaker by the same model the chain
uses after the meeting, on the processor. This puts a synthetic dialogue
through the real model and checks that the cut falls where the second
voice starts, and that one voice alone gives one label.

    pytest -m integration
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from tests.integration.prerequisites import (
    transcription_is_out_of_reach,
    voices_are_out_of_reach,
)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration

#: How far the model's cut may sit from the moment the second voice starts.
TOLERANCE_S = 1.0


@pytest.fixture(scope="session")
def segmenter():
    from greffier.wiring import slice_segmenter

    config = Config()
    out_of_reach = transcription_is_out_of_reach(config)
    if out_of_reach:
        pytest.skip(out_of_reach)
    return slice_segmenter(config)


@pytest.fixture(scope="session")
def dialogue(tmp_path_factory):
    out_of_reach = voices_are_out_of_reach(2)
    if out_of_reach:
        pytest.skip(out_of_reach)
    from make_meeting import make

    audio = make(tmp_path_factory.mktemp("audio") / "dialogue.wav")
    timeline = json.loads(audio.with_suffix(".timeline.json").read_text(encoding="utf-8"))
    return audio, timeline


def a_slice(audio: Path, start: float, end: float, destination: Path) -> Path:
    from greffier.application.watch import extract_slice

    found = extract_slice(audio, start, end, destination)
    assert found is not None
    return found


class TestTwoVoicesInOneSlice:
    def test_the_slice_is_cut_where_the_second_voice_starts(self, segmenter, dialogue, tmp_path):
        audio, timeline = dialogue
        change = next(line for line in timeline if line["speaker"] != timeline[0]["speaker"])
        start = max(0.0, change["start"] - 5.0)
        slice_ = a_slice(audio, start, start + 10.0, tmp_path / "deux.wav")
        turns = segmenter.turns(slice_)
        labels = {turn.voice for turn in turns}
        assert len(labels) >= 2, turns
        # The first label ends, and the second begins, around the change.
        first = timeline[0]["speaker"]
        expected = change["start"] - start
        ends = [t.span.end for t in turns if t.span.start < expected - TOLERANCE_S]
        starts = [t.span.start for t in turns if t.span.end > expected + TOLERANCE_S]
        assert first is not None and ends and starts
        assert min(abs(moment - expected) for moment in ends + starts) <= TOLERANCE_S

    def test_one_voice_alone_is_one_label(self, segmenter, dialogue, tmp_path):
        audio, timeline = dialogue
        line = timeline[0]
        length = min(line["end"] - line["start"], 10.0)
        slice_ = a_slice(audio, line["start"], line["start"] + length, tmp_path / "seule.wav")
        turns = segmenter.turns(slice_)
        assert turns and len({turn.voice for turn in turns}) == 1
