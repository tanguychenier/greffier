"""A Claude Code session kept warm for the whole meeting.

Measured on 2026-09-16: `claude -p` answers a one-sentence question in 4.6 s
with haiku, 5.0 s with sonnet, 6.2 s with opus, and almost all of it is the
process starting. The same process kept open and fed one message after
another answers the next ones in 1.3 s. Called by her name in a room, the
assistant cannot afford four seconds of silence before a word: this session
is what she thinks with while the meeting lasts.

The wire is Claude Code's own: `--input-format stream-json` takes one JSON
user message per line on stdin, `--output-format stream-json` gives one
event per line back, and a turn ends on a `result` event. The session also
remembers what was said before, which is what an exchange needs.

The guidance goes in as the system prompt, in place of Claude Code's own.
Measured on 2026-09-16 with sonnet on a real transcript: the first token
came after 2.6 to 2.9 s under the default system prompt, after 0.7 to 0.8 s
with the guidance alone, and a whole answer in 1.5 to 2.1 s instead of 5.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from typing import IO, Any

from greffier.adapters.writer_claude import _event, _is_a_search, guidance
from greffier.domain.as_it_comes import SentencesAsTheyCome

#: A turn that takes longer than this is abandoned, and the session with it:
#: the next question starts a fresh one rather than wait on a stuck process.
TURN_TIMEOUT = 60.0

#: Every turn hands the session what was said so far, and the session keeps
#: all of it. Past this many characters sent, it is replaced by a fresh one,
#: started right after the answer so that nobody waits for it: a session that
#: has swallowed a whole afternoon answers slower, then stops to compact.
RESTART_AFTER_CHARS = 200_000

#: The throwaway first turn, in the language of the guidance it follows.
PRIMING = "Réponds seulement « prête »."


class ClaudeSession:
    """Answers as a writer would, but from a process that stays open."""

    SEARCH_TOOLS = ("WebSearch", "WebFetch")

    def __init__(
        self,
        model: str = "",
        command: str = "claude",
        language: str = "",
        tools: tuple[str, ...] = (),
        own_guidance: str = "",
        on_search: Callable[[], None] | None = None,
        timeout: float = TURN_TIMEOUT,
    ) -> None:
        self.model = model
        self.command = command
        self.language = language
        self.tools = tools
        self.own_guidance = own_guidance
        self.on_search = on_search
        self.timeout = timeout
        self._process: subprocess.Popen[str] | None = None
        #: The guidance the running process was given as its system prompt.
        self._system_prompt = ""
        self._sent = 0
        self._lock = threading.Lock()

    def warm_up(self) -> None:
        """Starts the process now and makes it answer once, in the background.

        Starting it is not enough: the process settles on its first message,
        and measured with sonnet the first real question costs 5 s against
        2 s for the next ones. One throwaway turn, guidance included, pays that
        before anyone has spoken.
        """
        threading.Thread(target=self._prime, daemon=True).start()

    def _prime(self) -> None:
        with self._lock:
            try:
                process = self._running()
                self._one_turn(process, self._prompt(PRIMING))
            except (OSError, ValueError, RuntimeError):
                if self._process is not None:
                    self._drop(self._process)

    def write_up(self, transcription: str) -> str:
        return self.write_up_as_it_comes(transcription, None)

    def write_up_as_it_comes(
        self, transcription: str, on_sentence: Callable[[str], None] | None
    ) -> str:
        """The answer, and each of its sentences the moment it is finished.

        Measured on 2026-09-16 with sonnet, three sentences: the first one
        was whole at 2.6 s where the answer came back at 3.7. The voice
        starts on it while the model writes the rest. Only a session with
        no tools streams: with a search in the turn, the words before the
        search are not the answer, and the answer is what comes back at the
        end, as before.
        """
        streamed = on_sentence if not self.tools else None
        with self._lock:
            process = self._running()
            try:
                answer = self._one_turn(process, self._prompt(transcription), streamed)
            except TimeoutError:
                # Not retried: a question that took a minute would take two.
                self._drop(process)
                raise
            except (OSError, ValueError):
                # A broken pipe, a process gone: once more, on a fresh one.
                self._drop(process)
                process = self._running()
                try:
                    answer = self._one_turn(process, self._prompt(transcription), streamed)
                except (OSError, ValueError, TimeoutError):
                    self._drop(process)
                    raise
            if self._sent > RESTART_AFTER_CHARS:
                self._drop(process)
                self._running()
            return answer

    def _guidance(self) -> str:
        return self.own_guidance or guidance(self.language)

    def _prompt(self, text: str) -> str:
        """The message for this turn: the guidance ahead of it only when it
        is not the one the process already holds as its system prompt, the
        way a follow-up or a contribution swaps it for one call."""
        header = self._guidance()
        return text if header == self._system_prompt else header + text

    def close(self) -> None:
        with self._lock:
            if self._process is not None:
                self._drop(self._process)

    def _running(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        if shutil.which(self.command) is None:
            raise RuntimeError(
                f"« {self.command} » est introuvable dans le PATH. "
                "Installe Claude Code, ou bascule « compte_rendu.moteur » sur « ollama »."
            )
        self._system_prompt = self._guidance()
        command = [
            self.command, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--include-partial-messages",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--system-prompt", self._system_prompt,
            # Both: one says which tools exist, the other lets them run unasked.
            "--tools", ",".join(self.tools),
            "--allowed-tools", ",".join(self.tools),
        ]
        if self.model:
            command += ["--model", self.model]
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        return self._process

    def _one_turn(
        self,
        process: subprocess.Popen[str],
        prompt: str,
        on_sentence: Callable[[str], None] | None = None,
    ) -> str:
        stdin: IO[str] | None = process.stdin
        stdout: IO[str] | None = process.stdout
        if stdin is None or stdout is None:
            raise OSError("session sans tuyaux")
        message = {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": prompt}
        ]}}
        stdin.write(json.dumps(message) + "\n")
        stdin.flush()
        self._sent += len(prompt)
        answer: dict[str, Any] = {}
        reader = threading.Thread(
            target=self._read_until_the_result, args=(stdout, answer, on_sentence),
            daemon=True,
        )
        reader.start()
        reader.join(self.timeout)
        if reader.is_alive():
            raise TimeoutError("réponse trop longue")
        if "result" not in answer:
            raise OSError("session fermée avant la réponse")
        text = str(answer["result"] or "").strip()
        if answer.get("failed"):
            raise RuntimeError(f"Claude Code n'a rien produit : {text}")
        if not text:
            raise RuntimeError("Claude Code n'a rien produit.")
        return text

    def _read_until_the_result(
        self,
        stdout: IO[str],
        answer: dict[str, Any],
        on_sentence: Callable[[str], None] | None = None,
    ) -> None:
        already_searching = False
        cutter = SentencesAsTheyCome()
        for line in stdout:
            event = _event(line)
            if event is None:
                continue
            if not already_searching and _is_a_search(event, self.SEARCH_TOOLS):
                already_searching = True
                if self.on_search is not None:
                    self.on_search()
            if on_sentence is not None:
                for sentence in cutter.take(_words_of(event)):
                    on_sentence(sentence)
            if event.get("type") == "result":
                if on_sentence is not None and not event.get("is_error"):
                    for sentence in cutter.finish():
                        on_sentence(sentence)
                answer["result"] = event.get("result")
                answer["failed"] = bool(event.get("is_error"))
                return

    def _drop(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        if self._process is process:
            self._process = None
            self._sent = 0


def _words_of(event: dict[str, Any]) -> str:
    """The text a partial-message event carries, empty for every other one."""
    if event.get("type") != "stream_event":
        return ""
    inner = event.get("event") or {}
    if inner.get("type") != "content_block_delta":
        return ""
    delta = inner.get("delta") or {}
    if delta.get("type") != "text_delta":
        return ""
    return str(delta.get("text") or "")
