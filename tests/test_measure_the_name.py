"""`tools/measure_the_name.py`: whether her name is heard, take by take, no microphone here."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import measure_the_name  # noqa: E402

from greffier.domain.models import Span, Utterance  # noqa: E402


class HearsByFileName:
    """Says what the file name tells it to, seed or no seed."""

    def transcribe(self, audio: Path, language: str, prompt_seed: str) -> list[Utterance]:
        heard = audio.stem.replace("_", " ")
        if not prompt_seed:
            heard = heard.replace("Lucie", "Ici")
        return [Utterance(span=Span(0, 3), text=heard)]


class TestWhatWasHeard:
    def test_each_take_is_heard_with_the_seed_and_without(self, tmp_path, monkeypatch):
        from greffier import wiring

        monkeypatch.setattr(wiring, "light_transcriber", lambda config: HearsByFileName())
        takes = [tmp_path / "Lucie,_où_en_est_la_recette.wav", tmp_path / "bonjour_à_tous.wav"]
        for take in takes:
            take.touch()
        config = SimpleNamespace(assistant=SimpleNamespace(name="Lucie"))
        rows = measure_the_name.heard(takes, config)
        assert [r["heard_with_seed"] for r in rows] == [True, False]
        assert [r["heard_without_seed"] for r in rows] == [False, False]
        assert rows[0]["with_seed"] == "Lucie, où en est la recette"

    def test_the_questions_all_call_her_and_do_not_repeat(self):
        assert len(measure_the_name.QUESTIONS) == 10
        assert all(q.startswith("Lucie, ") for q in measure_the_name.QUESTIONS)
        assert len(set(measure_the_name.QUESTIONS)) == 10
