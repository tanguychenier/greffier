"""`tools/replay_follower.py`: the words of a live log fed to the follower again.

The transcriber is what makes a live measure slow; the attribution is what
a change to who-said-what touches. The replay cuts the slices the watch
cuts and hands the follower the sentences the log holds, so the tool is
judged in the time the voiceprints take. Here with no audio and no model:
what matters is that every sentence reaches the follower once, in the
slice it belongs to, on the slice's own clock.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import replay_follower  # noqa: E402


class TestTheSlices:
    def test_one_slice_per_period_each_reaching_back_over_the_previous(self):
        # The watch cuts from five seconds before what it processed: a
        # sentence astride two slices is whole in one of them.
        assert replay_follower.slices(30, period=10) == [(0, 10), (5, 20), (15, 30)]

    def test_the_last_slice_ends_where_the_recording_ends(self):
        assert replay_follower.slices(24, period=10)[-1] == (9, 24)

    def test_a_recording_shorter_than_a_period_is_one_slice(self):
        assert replay_follower.slices(4, period=10) == [(0, 4)]


class TestReadingTheLog:
    def test_only_the_turns_with_words_come_back_in_order(self, tmp_path):
        log = tmp_path / "reunion.jsonl"
        log.write_text("\n".join([
            json.dumps({"genre": "tour", "numero": 2, "debut": 6.0, "fin": 9.0, "texte": "deux"}),
            json.dumps({"genre": "reunion", "voix": "v2", "vers": "v1"}),
            json.dumps({"genre": "tour", "numero": 1, "debut": 0.0, "fin": 3.0, "texte": "un"}),
            json.dumps({"genre": "tour", "numero": 3, "debut": 9.0, "fin": 9.5, "texte": ""}),
            "",
        ]), encoding="utf-8")
        assert [t["texte"] for t in replay_follower.turns_of(log)] == ["un", "deux"]


class RecordingFollower:
    """Keeps what it was handed, slice by slice."""

    def __init__(self) -> None:
        self.handed: list[tuple[float, list[tuple[float, float, str]]]] = []
        self.thread = "the thread"

    def take_in(self, slice_, utterances, offset):
        self.handed.append(
            (offset, [(u.span.start, u.span.end, u.text) for u in utterances])
        )
        return []


@pytest.fixture
def a_log(tmp_path):
    log = tmp_path / "reunion.jsonl"
    log.write_text("\n".join(json.dumps(t) for t in [
        {"genre": "tour", "numero": 1, "debut": 1.0, "fin": 4.0, "texte": "bonjour"},
        {"genre": "tour", "numero": 2, "debut": 8.0, "fin": 12.0, "texte": "à cheval"},
        {"genre": "tour", "numero": 3, "debut": 13.0, "fin": 17.0, "texte": "ensuite"},
        {"genre": "tour", "numero": 4, "debut": 20.0, "fin": 25.0, "texte": "la fin"},
    ]), encoding="utf-8")
    return log


@pytest.fixture
def without_audio(monkeypatch, tmp_path):
    """No ffmpeg, no wav: the slice is a name and the length is given."""
    from types import SimpleNamespace

    import soundfile

    monkeypatch.setattr(soundfile, "info", lambda path: SimpleNamespace(duration=25.0))
    from greffier.application import watch

    monkeypatch.setattr(watch, "extract_slice",
                        lambda audio, start, end, destination: destination)


@pytest.mark.usefixtures("without_audio")
class TestFeedingTheFollower:
    def test_every_sentence_is_handed_once_in_the_slice_where_it_ends(self, a_log, tmp_path):
        follower = RecordingFollower()
        replay_follower.replay_through(follower, a_log, tmp_path / "reunion.wav", period=10.0)
        texts = [[u[2] for u in utterances] for _, utterances in follower.handed]
        # "à cheval" ends at 12 s: it is not heard by the slice that stops at
        # ten, and comes whole with the next one, as in the meeting.
        assert texts == [["bonjour"], ["à cheval", "ensuite"], ["la fin"]]

    def test_the_sentences_are_on_the_slice_s_own_clock(self, a_log, tmp_path):
        follower = RecordingFollower()
        replay_follower.replay_through(follower, a_log, tmp_path / "reunion.wav", period=10.0)
        offset, utterances = follower.handed[1]
        assert offset == 5.0
        assert utterances[0][:2] == (3.0, 7.0)

    def test_a_slice_with_nothing_new_is_skipped(self, a_log, tmp_path):
        follower = RecordingFollower()
        replay_follower.replay_through(follower, a_log, tmp_path / "reunion.wav", period=5.0)
        assert all(utterances for _, utterances in follower.handed)

    def test_the_thread_of_the_follower_is_what_comes_back(self, a_log, tmp_path):
        follower = RecordingFollower()
        thread = replay_follower.replay_through(follower, a_log, tmp_path / "reunion.wav", 10.0)
        assert thread == "the thread"
