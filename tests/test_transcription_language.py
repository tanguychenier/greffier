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
        vue: dict[str, list[str]] = {}

        def faux_run(command, **_options):
            vue["commande"] = list(command)
            # An empty .srt is enough: it is the command that is tested.
            Path(command[command.index("-of") + 1] + ".srt").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(
            "greffier.adapters.transcription_whisper_cpp.subprocess.run", faux_run)
        WhisperCppTranscriber(model).transcribe(model, language, "")
        return vue["commande"]

    def test_a_language_given_is_passed_on(self, monkeypatch, model):
        command = self._command(monkeypatch, model, "en")
        assert command[command.index("-l") + 1] == "en"

    def test_an_empty_language_becomes_auto(self, monkeypatch, model):
        """« -l » expects a value: without it, the next option would be swallowed."""
        command = self._command(monkeypatch, model, "")
        assert command[command.index("-l") + 1] == "auto"


class TestFasterWhisper:
    def _langue_recue(self, monkeypatch, language):
        from greffier.adapters import transcription_faster_whisper as adaptateur

        vue: dict[str, object] = {}

        class FakeModel:
            def transcribe(self, _audio, **options):
                vue["language"] = options.get("language")
                return iter(()), None

        transcriber = adaptateur.FasterWhisperTranscriber.__new__(
            adaptateur.FasterWhisperTranscriber)
        monkeypatch.setattr(transcriber, "_load", lambda: FakeModel(), raising=False)
        transcriber.transcribe(Path("essai.wav"), language, "")
        return vue["language"]

    def test_a_language_given_is_passed_on(self, monkeypatch):
        assert self._langue_recue(monkeypatch, "es") == "es"

    def test_an_empty_language_becomes_none(self, monkeypatch):
        """The string « auto » would be refused: it is the absence that triggers
        the detection."""
        assert self._langue_recue(monkeypatch, "") is None
