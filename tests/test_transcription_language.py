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
    def _command(self, monkeypatch, model, language, device="auto"):
        view: dict[str, list[str]] = {}

        def fake_run(command, **_options):
            view["commande"] = list(command)
            # An empty .srt is enough: it is the command that is tested.
            Path(command[command.index("-of") + 1] + ".srt").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(
            "greffier.adapters.transcription_whisper_cpp.subprocess.run", fake_run)
        WhisperCppTranscriber(model, device=device).transcribe(model, language, "")
        return view["commande"]

    def test_a_language_given_is_passed_on(self, monkeypatch, model):
        command = self._command(monkeypatch, model, "en")
        assert command[command.index("-l") + 1] == "en"

    def test_an_empty_language_becomes_auto(self, monkeypatch, model):
        """« -l » expects a value: without it, the next option would be swallowed."""
        command = self._command(monkeypatch, model, "")
        assert command[command.index("-l") + 1] == "auto"

    def test_a_cpu_choice_disables_the_graphics_backend(self, monkeypatch, model):
        command = self._command(monkeypatch, model, "fr", device="cpu")
        assert "--no-gpu" in command

    def test_an_automatic_choice_keeps_the_native_graphics_backend(self, monkeypatch, model):
        command = self._command(monkeypatch, model, "fr")
        assert "--no-gpu" not in command


@pytest.mark.parametrize("factory", ["_transcriber", "light_transcriber", "dictation_transcriber"])
def test_the_cpu_choice_reaches_every_whisper_cpp_path(monkeypatch, tmp_path, factory):
    from greffier import wiring
    from greffier.adapters.configuration import Config

    (tmp_path / "ggml-large-v3-turbo.bin").write_bytes(b"model fixture")
    config = Config()
    config.paths.models = tmp_path
    config.transcription.engine = "whisper.cpp"
    config.hardware.device = "cpu"
    monkeypatch.setattr(wiring, "_the_card_first", lambda _config: None)
    monkeypatch.setattr(wiring, "_live_model", lambda _config: "large-v3-turbo")
    transcriber = getattr(wiring, factory)(config)
    assert transcriber.device == "cpu"


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
        monkeypatch.setattr(transcriber, "_load", FakeModel, raising=False)
        transcriber.transcribe(Path("essai.wav"), language, "")
        return view["language"]

    def test_a_language_given_is_passed_on(self, monkeypatch):
        assert self._language_received(monkeypatch, "es") == "es"

    def test_an_empty_language_becomes_none(self, monkeypatch):
        """The string « auto » would be refused: it is the absence that triggers
        the detection."""
        assert self._language_received(monkeypatch, "") is None


@pytest.mark.parametrize(("available", "expected"), [(3, 3), (16, 4), (None, 1)])
def test_native_default_threads_fit_the_machine(monkeypatch, model, available, expected):
    monkeypatch.setattr(
        "greffier.adapters.transcription_whisper_cpp.os.cpu_count", lambda: available,
    )
    assert WhisperCppTranscriber(model).threads == expected


def test_explicit_native_threads_are_preserved(model):
    assert WhisperCppTranscriber(model, threads=6).threads == 6


@pytest.mark.parametrize("explicit", [False, True])
def test_native_worker_environment_is_local_and_preserves_choices(monkeypatch, model, explicit):
    import os

    captured = {}
    for key in ["OMP_WAIT_POLICY", "VECLIB_MAXIMUM_THREADS"]:
        monkeypatch.delenv(key, raising=False)
    if explicit:
        monkeypatch.setenv("OMP_WAIT_POLICY", "ACTIVE")
        monkeypatch.setenv("VECLIB_MAXIMUM_THREADS", "2")
    before = dict(os.environ)

    def fake_run(command, **options):
        captured.update(options["env"])
        Path(command[command.index("-of") + 1] + ".srt").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("greffier.adapters.transcription_whisper_cpp.subprocess.run", fake_run)
    WhisperCppTranscriber(model).transcribe(model, "fr", "")
    assert captured["OMP_WAIT_POLICY"] == ("ACTIVE" if explicit else "PASSIVE")
    assert captured["VECLIB_MAXIMUM_THREADS"] == ("2" if explicit else "1")
    assert dict(os.environ) == before


def test_a_present_native_vad_is_not_automatically_enabled(monkeypatch, tmp_path):
    from greffier import wiring
    from greffier.adapters.configuration import Config

    (tmp_path / "ggml-large-v3-turbo.bin").write_bytes(b"model fixture")
    (tmp_path / "ggml-silero-v5.1.2.bin").write_bytes(b"present detector fixture")
    config = Config()
    config.paths.models = tmp_path
    config.transcription.engine = "whisper.cpp"
    monkeypatch.setattr(wiring, "_the_card_first", lambda _config: None)
    assert wiring._transcriber(config).vad is None
