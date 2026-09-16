"""The session kept warm for the assistant, driven through real pipes.

A fake `claude` stands in: it speaks the same wire (one JSON message per line
in, stream-json events out) and says which process answered, so that a test
can tell a kept session from a restarted one.
"""

from __future__ import annotations

import stat
import sys
import time
from pathlib import Path

import pytest

from greffier.adapters import brain_claude
from greffier.adapters.brain_claude import ClaudeSession

FAKE = '''#!{python}
import json, os, sys, time
argv_file = os.environ.get("FAKE_CLAUDE_ARGV")
if argv_file:
    open(argv_file, "a").write(json.dumps(sys.argv[1:]) + "\\n")
turns = 0
for line in sys.stdin:
    message = json.loads(line)
    text = message["message"]["content"][0]["text"]
    turns += 1
    if os.environ.get("FAKE_CLAUDE_SEARCH"):
        print(json.dumps({{"type": "assistant", "message": {{"content": [
            {{"type": "tool_use", "name": "WebSearch", "input": {{}}}}]}}}}), flush=True)
    time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
    for piece in os.environ.get("FAKE_CLAUDE_PIECES", "").split("|"):
        if piece:
            print(json.dumps({{"type": "stream_event", "event": {{
                "type": "content_block_delta",
                "delta": {{"type": "text_delta", "text": piece}}}}}}), flush=True)
            time.sleep(0.01)
    if os.environ.get("FAKE_CLAUDE_FAIL"):
        print(json.dumps({{"type": "result", "is_error": True,
                           "result": "quota exceeded"}}), flush=True)
    else:
        print(json.dumps({{"type": "result", "result":
            f"pid {{os.getpid()}} turn {{turns}} head [{{text[:12]}}] tail [{{text[-14:]}}]"}}),
            flush=True)
    if turns >= int(os.environ.get("FAKE_CLAUDE_DIE_AFTER", "999")):
        sys.exit(0)
'''


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch) -> Path:
    script = tmp_path / "claude"
    script.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    for knob in ("FAKE_CLAUDE_SEARCH", "FAKE_CLAUDE_SLEEP", "FAKE_CLAUDE_FAIL",
                 "FAKE_CLAUDE_DIE_AFTER", "FAKE_CLAUDE_ARGV", "FAKE_CLAUDE_PIECES"):
        monkeypatch.delenv(knob, raising=False)
    return script


def _pid(answer: str) -> str:
    return answer.split()[1]


def _argv(file: Path) -> list[list[str]]:
    """One command line per process the fake was started as."""
    import json

    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]


class TestOneSessionForTheWholeMeeting:
    def test_two_questions_are_answered_by_the_same_process(self, fake_claude):
        session = ClaudeSession(command=str(fake_claude), own_guidance="G. ")
        try:
            first = session.write_up("Lucie, où en est le lot 2 ?")
            second = session.write_up("Et le lot 3 ?")
        finally:
            session.close()
        assert _pid(first) == _pid(second)
        assert "turn 1" in first and "turn 2" in second

    def test_the_guidance_is_the_system_prompt_and_a_question_carries_only_itself(
        self, fake_claude, tmp_path, monkeypatch
    ):
        """Measured: the first token came after 2.6 to 2.9 s under Claude
        Code's own system prompt, after 0.7 to 0.8 s with the guidance alone.
        """
        argv = tmp_path / "argv"
        monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(argv))
        session = ClaudeSession(command=str(fake_claude), own_guidance="Réponds court. ")
        try:
            answer = session.write_up("Lucie, quelle heure ?")
        finally:
            session.close()
        assert "head [Lucie, quell]" in answer
        assert "tail [quelle heure ?]" in answer
        line = _argv(argv)[0]
        assert line[line.index("--system-prompt") + 1] == "Réponds court. "

    def test_the_guidance_can_change_between_two_turns(self, fake_claude):
        """`_interrogate` swaps the guidance for one call: that call carries it."""
        session = ClaudeSession(command=str(fake_claude), own_guidance="AAAAAAAAAAAA ")
        try:
            session.write_up("un")
            session.own_guidance = "BBBBBBBBBBBB "
            answer = session.write_up("deux")
            session.own_guidance = "AAAAAAAAAAAA "
            back = session.write_up("trois")
        finally:
            session.close()
        assert "head [BBBBBBBBBBBB]" in answer
        assert "head [trois]" in back, "the process still holds the first guidance"

    def test_warming_up_makes_the_process_answer_once_before_the_first_question(
        self, fake_claude
    ):
        session = ClaudeSession(command=str(fake_claude), own_guidance="G ")
        try:
            session.warm_up()
            answer = session.write_up("Lucie ?")
            started = session._process
            assert started is not None and started.poll() is None
            assert _pid(answer) == str(started.pid)
            assert "turn 2" in answer, "the throwaway turn came first"
        finally:
            session.close()

    def test_a_warm_up_that_fails_costs_nothing(self, tmp_path):
        session = ClaudeSession(command=str(tmp_path / "nowhere"))
        session.warm_up()
        time.sleep(0.2)
        assert session._process is None

    def test_closing_ends_the_process(self, fake_claude):
        session = ClaudeSession(command=str(fake_claude))
        session.write_up("Lucie ?")
        process = session._process
        session.close()
        assert process is not None and process.poll() is not None
        assert session._process is None


class TestTheSessionSurvivesItsProcess:
    def test_a_dead_process_is_replaced_without_losing_the_question(
        self, fake_claude, monkeypatch
    ):
        monkeypatch.setenv("FAKE_CLAUDE_DIE_AFTER", "1")
        session = ClaudeSession(command=str(fake_claude))
        try:
            first = session.write_up("un")
            second = session.write_up("deux")
        finally:
            session.close()
        assert _pid(first) != _pid(second)
        assert "turn 1" in second, "the fresh process answered the second question"

    def test_a_turn_too_long_is_abandoned_and_the_next_one_starts_afresh(
        self, fake_claude, monkeypatch
    ):
        monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "3")
        session = ClaudeSession(command=str(fake_claude), timeout=0.3)
        try:
            with pytest.raises(TimeoutError):
                session.write_up("un")
            assert session._process is None, "the stuck process is not kept"
            monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "0")
            session.timeout = 10.0
            assert "turn 1" in session.write_up("deux")
        finally:
            session.close()

    def test_a_slow_answer_is_not_asked_twice(self, fake_claude, tmp_path, monkeypatch):
        """A question that took a minute must not take two."""
        spawns = tmp_path / "spawns"
        monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(spawns))
        monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "0.5")
        session = ClaudeSession(command=str(fake_claude), timeout=0.2)
        try:
            with pytest.raises(TimeoutError):
                session.write_up("un")
        finally:
            session.close()
        assert len(_argv(spawns)) == 1

    def test_a_session_that_swallowed_too_much_is_replaced_after_the_answer(
        self, fake_claude, monkeypatch
    ):
        monkeypatch.setattr(brain_claude, "RESTART_AFTER_CHARS", 30)
        session = ClaudeSession(command=str(fake_claude), own_guidance="G ")
        try:
            first = session.write_up("x" * 20)
            second = session.write_up("y" * 20)
            third = session.write_up("z")
        finally:
            session.close()
        assert _pid(first) == _pid(second), "the budget is checked after the answer"
        assert _pid(second) != _pid(third)

    def test_an_error_result_is_an_error(self, fake_claude, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
        session = ClaudeSession(command=str(fake_claude))
        try:
            with pytest.raises(RuntimeError, match="quota exceeded"):
                session.write_up("un")
        finally:
            session.close()

    def test_a_missing_command_says_so(self, tmp_path):
        session = ClaudeSession(command=str(tmp_path / "nowhere"))
        with pytest.raises(RuntimeError, match="introuvable"):
            session.write_up("un")


class TestWhatTheProcessIsToldOnTheWire:
    def test_the_command_line_opens_a_stream_session_with_the_model(
        self, fake_claude, tmp_path, monkeypatch
    ):
        argv = tmp_path / "argv"
        monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(argv))
        session = ClaudeSession(command=str(fake_claude), model="haiku",
                                tools=("WebSearch", "WebFetch"))
        try:
            session.write_up("un")
        finally:
            session.close()
        line = " ".join(_argv(argv)[0])
        assert "--input-format stream-json" in line
        assert "--output-format stream-json" in line
        assert "--strict-mcp-config" in line
        assert "--no-session-persistence" in line
        assert "--tools WebSearch,WebFetch --allowed-tools WebSearch,WebFetch" in line
        assert "--model haiku" in line

    def test_with_no_tool_the_process_is_told_it_has_none(
        self, fake_claude, tmp_path, monkeypatch
    ):
        argv = tmp_path / "argv"
        monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(argv))
        session = ClaudeSession(command=str(fake_claude))
        try:
            session.write_up("un")
        finally:
            session.close()
        line = _argv(argv)[0]
        assert line[line.index("--tools") + 1] == ""

    def test_the_cue_sounds_once_when_a_turn_searches(self, fake_claude, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_SEARCH", "1")
        cues: list[int] = []
        session = ClaudeSession(command=str(fake_claude), on_search=lambda: cues.append(1))
        try:
            session.write_up("un")
            session.write_up("deux")
        finally:
            session.close()
        assert cues == [1, 1], "one cue per answer that searched"

    def test_the_cue_stays_silent_on_a_plain_answer(self, fake_claude):
        cues: list[int] = []
        session = ClaudeSession(command=str(fake_claude), on_search=lambda: cues.append(1))
        try:
            session.write_up("un")
        finally:
            session.close()
        assert cues == []

    def test_what_the_process_writes_on_stderr_never_reaches_the_terminal(self, fake_claude):
        session = ClaudeSession(command=str(fake_claude))
        try:
            session.write_up("un")
            assert session._process is not None
            assert session._process.stderr is None, "sent to the void, not inherited"
        finally:
            session.close()


class TestTheSentencesComeAsTheModelWritesThem:
    """Measured with sonnet, three sentences: the first was whole at 2.6 s where
    the answer came back at 3.7. The session hands each finished sentence
    over, and the whole answer at the end as before."""

    PIECES = "Oui, je vous en|tends. La recette est| jeudi. Voi|là."

    def test_each_finished_sentence_is_handed_over_before_the_answer(
        self, fake_claude, monkeypatch
    ):
        monkeypatch.setenv("FAKE_CLAUDE_PIECES", self.PIECES)
        heard: list[tuple[str, bool]] = []
        done = {"answer": False}
        session = ClaudeSession(command=str(fake_claude), own_guidance="G. ")
        try:
            answer = session.write_up_as_it_comes(
                "Lucie ?", lambda sentence: heard.append((sentence, done["answer"]))
            )
            done["answer"] = True
        finally:
            session.close()
        assert [sentence for sentence, _ in heard] == [
            "Oui, je vous entends.", "La recette est jeudi.", "Voilà."
        ]
        assert all(not after for _, after in heard)
        assert "turn 1" in answer

    def test_the_partial_messages_are_asked_for(self, fake_claude, tmp_path, monkeypatch):
        argv = tmp_path / "argv"
        monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(argv))
        session = ClaudeSession(command=str(fake_claude), own_guidance="G. ")
        try:
            session.write_up("Lucie ?")
        finally:
            session.close()
        assert "--include-partial-messages" in _argv(argv)[0]

    def test_a_session_with_tools_keeps_the_answer_for_the_end(
        self, fake_claude, monkeypatch
    ):
        # The words before a search are not the answer.
        monkeypatch.setenv("FAKE_CLAUDE_PIECES", self.PIECES)
        heard: list[str] = []
        session = ClaudeSession(
            command=str(fake_claude), own_guidance="G. ", tools=("WebSearch",)
        )
        try:
            answer = session.write_up_as_it_comes("Lucie ?", heard.append)
        finally:
            session.close()
        assert heard == [] and "turn 1" in answer

    def test_nothing_is_handed_over_on_a_failed_turn(self, fake_claude, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_PIECES", "Un début")
        monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
        heard: list[str] = []
        session = ClaudeSession(command=str(fake_claude), own_guidance="G. ")
        try:
            with pytest.raises(RuntimeError):
                session.write_up_as_it_comes("Lucie ?", heard.append)
        finally:
            session.close()
        assert heard == []

    def test_write_up_alone_streams_nothing_and_still_answers(self, fake_claude, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_PIECES", self.PIECES)
        session = ClaudeSession(command=str(fake_claude), own_guidance="G. ")
        try:
            assert "turn 1" in session.write_up("Lucie ?")
        finally:
            session.close()
