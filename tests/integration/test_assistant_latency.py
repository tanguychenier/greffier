"""The assistant called three times on a replayed meeting, the whole chain.

The bench `tools/measure_assistant.py` gives the figures; this test guards
what the figures rest on: her name is heard on real sound the moment the
question ends, every question gets one answer and not two, and a question
that was still being said is not answered in halves. The brain is doubled
so that the test needs no account, and the loudspeaker is a clock.

    pytest -m integration tests/integration/test_assistant_latency.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from tests.integration.prerequisites import (
    the_called_name_is_out_of_reach,
    transcription_is_out_of_reach,
)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration


class CannedBrain:
    """Answers each question with the words it was asked, instantly."""

    def __init__(self) -> None:
        self.own_guidance = ""
        self.asked: list[str] = []

    def write_up(self, text: str) -> str:
        self.asked.append(text)
        return "Je note la question."


@pytest.fixture(scope="module")
def replayed():
    out_of_reach = the_called_name_is_out_of_reach() or transcription_is_out_of_reach(Config())
    if out_of_reach:
        pytest.skip(out_of_reach)
    import measure_assistant as bench

    with tempfile.TemporaryDirectory() as folder:
        audio, timeline = bench._meeting(Path(folder))
        config = Config()
        config.paths.data = Path(folder) / "data"
        config.assistant.active = True
        config.live.active = True
        brain = CannedBrain()
        clock = bench.replay(audio, config, "", brain=brain)
        yield bench.delays(timeline, clock, config.assistant.name), clock, brain


class TestCalledThreeTimesSheAnswersThreeTimes:
    def test_every_question_is_heard_and_answered(self, replayed):
        rows, _, _ = replayed
        assert len(rows) == 3
        assert all(row["spotted"] is not None for row in rows), rows
        assert all(row["ready"] is not None for row in rows), rows

    def test_she_is_asked_once_per_question(self, replayed):
        """A pass that read half the question, then the whole of it, asked twice."""
        _, clock, brain = replayed
        assert len(brain.asked) == 3, brain.asked
        assert len([e for e in clock.events if e[0] == "spotted"]) == 3

    def test_she_is_asked_the_whole_question(self, replayed):
        _, _, brain = replayed
        assert any("anomalies" in q and "valider" in q for q in brain.asked), brain.asked
        assert any("jour" in q and "recette" in q for q in brain.asked), brain.asked

    def test_her_name_is_heard_within_the_room_s_patience(self, replayed):
        """Not a benchmark: the bench is. A bound a broken chain cannot meet."""
        rows, _, _ = replayed
        assert all(row["spotted"] < 8.0 for row in rows), rows
