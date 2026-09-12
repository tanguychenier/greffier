"""The sound that says the assistant is looking something up.

Called by its name it takes a few seconds to answer, and nothing said whether
it was thinking or searching. A cue only means something if it sounds when a
search really starts -- one that sounded on every question would say nothing.
"""

from __future__ import annotations

import json

import pytest

from greffier.adapters.writer_claude import ClaudeWriter


def _stream(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def _search(name: str = "WebSearch") -> dict:
    return {"type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name,
                                     "input": {"query": "recette"}}]}}


def _answer(text: str) -> dict:
    return {"type": "result", "result": text}


class FakeProcess:
    def __init__(self, sortie: str, code: int = 0):
        self.stdout = iter(sortie.splitlines(keepends=True))
        self.stderr = _Err()
        self.returncode = code

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _Err:
    def read(self):
        return ""


@pytest.fixture
def sonne(monkeypatch):
    """A writer whose call is replayed from a recorded stream."""
    sonneries: list[int] = []

    def writer(sortie: str, code: int = 0) -> ClaudeWriter:
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(
            "subprocess.Popen", lambda *a, **k: FakeProcess(sortie, code)
        )
        return ClaudeWriter(on_search=lambda: sonneries.append(1))

    writer.sonneries = sonneries  # type: ignore[attr-defined]
    return writer


class TestTheCueSoundsOnASearch:
    def test_it_sounds_when_a_search_starts(self, sonne):
        writer = sonne(_stream(_search(), _answer("Il reste deux anomalies.")))
        assert writer.write_up("...") == "Il reste deux anomalies."
        assert sonne.sonneries == [1]

    def test_it_sounds_once_for_a_search_repeated(self, sonne):
        """Three queries in a row are one question for the room."""
        writer = sonne(_stream(_search(), _search("WebFetch"), _answer("Oui.")))
        writer.write_up("...")
        assert sonne.sonneries == [1], "une seule pastille par réponse"

    def test_a_plain_answer_stays_silent(self, sonne):
        writer = sonne(_stream(_answer("Jeudi.")))
        assert writer.write_up("...") == "Jeudi."
        assert sonne.sonneries == []

    def test_a_line_that_is_not_an_event_costs_nothing(self, sonne):
        """A stream is not a contract: a warning in front must change nothing."""
        writer = sonne("warning: something\n" + _stream(_search(), _answer("Oui.")))
        assert writer.write_up("...") == "Oui."
        assert sonne.sonneries == [1]

    def test_nothing_answered_is_still_an_error(self, sonne):
        writer = sonne(_stream(_search()), code=1)
        with pytest.raises(RuntimeError):
            writer.write_up("...")


class TestWithoutTheCue:
    def test_the_plain_text_output_is_kept(self, monkeypatch):
        """The minutes have no use for the stream, and it costs more to read."""
        vu: dict[str, list[str]] = {}

        class Outcome:
            returncode = 0
            stdout = "Le compte rendu."
            stderr = ""

        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(
            "subprocess.run",
            lambda command, **k: vu.setdefault("command", command) and None or Outcome(),
        )
        assert ClaudeWriter().write_up("...") == "Le compte rendu."
        assert "text" in vu["command"] and "stream-json" not in vu["command"]


class TestTheSoundItself:
    def test_the_file_ships_with_the_package(self):
        from greffier.adapters.cue_sound import WEB_SEARCH

        assert WEB_SEARCH.exists(), "le son doit suivre l'installation, pas le dépôt"

    def test_it_is_far_below_the_voices(self):
        """A cue at the level of the people talking is an interruption."""
        import soundfile

        from greffier.adapters.cue_sound import WEB_SEARCH

        son, taux = soundfile.read(str(WEB_SEARCH))
        crete = max(abs(son.min()), abs(son.max()))
        assert crete < 0.2, f"crête {crete:.2f} : trop fort pour une pastille"
        assert len(son) / taux < 0.6, "une pastille ne dure pas"

    def test_with_no_player_it_stays_silent(self, monkeypatch):
        from greffier.adapters import cue_sound

        monkeypatch.setattr("greffier.adapters.voice_neural.player", lambda: None)
        cue_sound.cue()()  # ne doit rien lever

    def test_a_missing_file_stays_silent(self, monkeypatch, tmp_path):
        from greffier.adapters import cue_sound

        monkeypatch.setattr(
            "greffier.adapters.voice_neural.player", lambda: ["/bin/true"]
        )
        cue_sound.cue(tmp_path / "parti.wav")()  # ne doit rien lever
