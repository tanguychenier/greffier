"""The delays `tools/measure_assistant.py` reads off its clock, counted by hand."""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

from measure_assistant import Clock, delays  # noqa: E402


def _clock(*events: tuple[str, float, str]) -> Clock:
    clock = Clock()
    clock.events = list(events)
    return clock


TIMELINE = [
    {"speaker": "A", "text": "Bonjour à tous.", "start": 0.0, "end": 2.0},
    {"speaker": "A", "text": "Lucie, combien d'anomalies ?", "start": 3.0, "end": 6.0},
    {"speaker": "B", "text": "On décale la recette.", "start": 18.0, "end": 21.0},
    {"speaker": "A", "text": "Lucie, à quel jour ?", "start": 22.0, "end": 24.0},
]


class TestReadingTheDelays:
    def test_each_delay_is_counted_from_the_end_of_its_question(self):
        clock = _clock(("spotted", 8.0, "combien"), ("asked", 8.1, ""),
                       ("answered", 9.5, "Deux."), ("ready", 9.9, "0.wav"),
                       ("spotted", 26.0, "jour"), ("answered", 27.0, "Jeudi."),
                       ("ready", 27.4, "0.wav"))
        rows = delays(TIMELINE, clock, "Lucie")
        assert [r["spotted"] for r in rows] == [2.0, 2.0]
        assert [r["answered"] for r in rows] == [3.5, 3.0]
        assert [r["ready"] for r in rows] == [3.9, 3.4]
        assert rows[0]["answer"] == "Deux."

    def test_a_question_with_no_answer_shows_nothing(self):
        clock = _clock(("spotted", 26.0, "jour"), ("answered", 27.0, "Jeudi."))
        rows = delays(TIMELINE, clock, "Lucie")
        assert rows[0] == {"question": "Lucie, combien d'anomalies ?", "spotted": None,
                           "answered": None, "ready": None, "answer": ""}
        assert rows[1]["ready"] is None

    def test_an_event_belongs_to_the_last_question_asked_before_it(self):
        """An answer that lands after the next question is the next question's."""
        clock = _clock(("spotted", 23.0, "late"), ("answered", 25.0, "Tard."))
        rows = delays(TIMELINE, clock, "Lucie")
        assert rows[0]["spotted"] is None
        assert rows[1]["spotted"] == -1.0 and rows[1]["answered"] == 1.0
