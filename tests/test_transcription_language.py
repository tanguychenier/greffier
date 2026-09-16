"""What the two engines receive as a language.

The empty setting means « recognise it yourself ». The two engines express it
differently, and getting it wrong is silent: whisper.cpp would transcribe in
an arbitrary language, faster-whisper would refuse an unknown code, in both
cases an hour after the start of the meeting.
"""

import subprocess
from pathlib import Path

import pytest

from greffier.adapters.transcription_whisper_cpp import WhisperCppTranscriber


@pytest.fixture
def model(tmp_path):
    file = tmp_path / "ggml-small.bin"
    file.write_bytes(b"\0" * 16)
    return file


class TestWhisperCpp:
    def _command(self, monkeypatch, model, language):
        view: dict[str, list[str]] = {}

        def fake_run(command, **_options):
            view["commande"] = list(command)
            # An empty .srt is enough: it is the command that is tested.
            Path(command[command.index("-of") + 1] + ".srt").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(
            "greffier.adapters.transcription_whisper_cpp.subprocess.run", fake_run)
        WhisperCppTranscriber(model).transcribe(model, language, "")
        return view["commande"]

    def test_a_language_given_is_passed_on(self, monkeypatch, model):
        command = self._command(monkeypatch, model, "en")
        assert command[command.index("-l") + 1] == "en"

    def test_an_empty_language_becomes_auto(self, monkeypatch, model):
        """« -l » expects a value: without it, the next option would be swallowed."""
        command = self._command(monkeypatch, model, "")
        assert command[command.index("-l") + 1] == "auto"


class TestFasterWhisper:
    def _language_received(self, monkeypatch, language):
        from greffier.adapters import transcription_faster_whisper as adapter

        view: dict[str, object] = {}

        class FakeModel:
            def transcribe(self, _audio, **options):
                view["language"] = options.get("language")
                return iter(()), None

        transcriber = adapter.FasterWhisperTranscriber.__new__(
            adapter.FasterWhisperTranscriber)
        monkeypatch.setattr(transcriber, "_load", lambda: FakeModel(), raising=False)
        transcriber.transcribe(Path("essai.wav"), language, "")
        return view["language"]

    def test_a_language_given_is_passed_on(self, monkeypatch):
        assert self._language_received(monkeypatch, "es") == "es"

    def test_an_empty_language_becomes_none(self, monkeypatch):
        """The string « auto » would be refused: it is the absence that triggers
        the detection."""
        assert self._language_received(monkeypatch, "") is None
