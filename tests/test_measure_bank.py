"""The verdict of `tools/measure_bank.py`, on cases small enough to count by hand."""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

from measure_bank import judged, person_of_each_voice  # noqa: E402
from measure_corpus import Sentence  # noqa: E402


def turn(speaker: str, start: float, end: float) -> dict:
    return {"speaker": speaker, "start": start, "end": end, "text": "..."}


class TestWhoEachVoiceIs:
    def test_a_voice_is_the_person_it_mostly_carries(self):
        sentences = [Sentence(0, 5, "a", "v1"), Sentence(5, 10, "b", "v1"),
                     Sentence(10, 15, "c", "v1")]
        turns = [turn("084", 0, 10), turn("085", 10, 15)]
        assert person_of_each_voice(sentences, turns) == {"v1": "084"}

    def test_a_scrap_of_a_voice_is_not_named(self):
        """Ten seconds at least: a voice of two seconds is noise, not a person."""
        sentences = [Sentence(0, 2, "a", "v1"), Sentence(2, 22, "b", "v2")]
        turns = [turn("084", 0, 2), turn("085", 2, 22)]
        assert person_of_each_voice(sentences, turns) == {"v2": "085"}


class TestTheVerdictOnTheSecondMeeting:
    def _sentences(self):
        return [Sentence(0, 5, "a", "v1"), Sentence(5, 10, "b", "v1"),
                Sentence(10, 15, "c", "v2"), Sentence(15, 20, "d", "v3")]

    def _turns(self):
        return [turn("084", 0, 10), turn("085", 10, 15), turn("086", 15, 20)]

    def test_right_wrong_and_nobody_are_counted_per_person(self):
        verdict = judged(self._sentences(), {"v1": "Alice", "v2": "Diane"}, self._turns())
        assert (verdict["right"], verdict["wrong"], verdict["nobody"]) == (2, 1, 1)
        assert verdict["per_person"]["Alice"] == {"right": 2, "voices": 1}
        assert verdict["per_person"]["Bruno"] == {"wrong": 1, "voices": 1}
        assert verdict["per_person"]["Chloé"] == {"nobody": 1, "voices": 1}

    def test_a_person_split_in_two_voices_shows_two(self):
        sentences = [Sentence(0, 5, "a", "v1"), Sentence(5, 10, "b", "v9")]
        verdict = judged(sentences, {"v1": "Alice", "v9": "Alice"}, [turn("084", 0, 10)])
        assert verdict["per_person"]["Alice"] == {"right": 2, "voices": 2}

    def test_a_sentence_the_reference_does_not_cover_is_not_judged(self):
        sentences = [Sentence(0, 5, "a", "v1"), Sentence(50, 55, "b", "v1")]
        verdict = judged(sentences, {"v1": "Alice"}, [turn("084", 0, 5)])
        assert verdict["right"] + verdict["wrong"] + verdict["nobody"] == 1

    def test_a_live_voice_with_no_name_yet_is_nobody(self):
        sentences = [Sentence(0, 5, "a", "v1")]
        verdict = judged(sentences, {"v1": None}, [turn("084", 0, 5)])
        assert verdict["nobody"] == 1
