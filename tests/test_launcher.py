"""The packaged launcher does what `greffier fenetre` does, and nothing it cannot do.

Never run on a real Windows as these tests are written; what a runner showed
on 2026-09-15 is that the launcher called a method the window no longer had,
and that the executable had no sentences to show. Neither survives here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import launcher  # noqa: E402


class FakeWindow:
    spun = False

    def __init__(self, config) -> None:
        self.config = config

    def spin(self) -> None:
        FakeWindow.spun = True


class TestStarting:
    def test_the_launcher_calls_the_method_the_window_has(self, monkeypatch, tmp_path):
        from greffier.interface import window

        monkeypatch.setattr(window, "Window", FakeWindow)
        monkeypatch.setattr(launcher, "log", lambda: tmp_path / "demarrage.log")
        monkeypatch.setattr(sys, "argv", ["Greffier.exe"])
        FakeWindow.spun = False
        assert launcher.main() == 0
        assert FakeWindow.spun
        assert not (tmp_path / "demarrage.log").exists()

    def test_the_method_it_calls_exists_on_the_real_window(self):
        from greffier.interface.window import Window

        assert callable(getattr(Window, "spin", None))

    def test_version_answers_without_opening_anything(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["Greffier.exe", "--version"])
        assert launcher.main() == 0
        assert capsys.readouterr().out.startswith("Greffier ")


class TestWhatTheExecutableCarries:
    @pytest.mark.parametrize("workflow", ["release.yml", "windows-proof.yml"])
    def test_the_sentences_and_the_sounds_travel_with_the_executable(self, workflow):
        text = (RACINE / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "--collect-data greffier" in text


def test_a_packaged_helpers_command_reaches_the_cli(monkeypatch):
    from greffier import cli

    received = []
    monkeypatch.setattr(cli, "application", lambda: received.append(list(sys.argv)))
    monkeypatch.setattr(
        sys, "argv", ["Greffier.exe", "-m", "greffier", "assister", "--config", "test.toml"],
    )
    FakeWindow.spun = False
    assert launcher.main() == 0
    assert received == [["Greffier.exe", "assister", "--config", "test.toml"]]
    assert FakeWindow.spun is False


def test_a_windowed_helpers_output_is_kept_and_restored(monkeypatch, tmp_path):
    from greffier import cli

    trace = tmp_path / "helper.log"
    monkeypatch.setenv("GREFFIER_COMPANION_LOG", str(trace))
    monkeypatch.setattr(sys, "argv", ["Greffier.exe", "-m", "greffier", "assister"])
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(cli, "application", lambda: print("helper started"))
    assert launcher.main() == 0
    assert sys.stdout is None and sys.stderr is None
    assert "helper started" in trace.read_text()


def test_the_real_decoder_and_bundled_vad_read_audio_without_transcription_weights(tmp_path):
    pytest.importorskip("faster_whisper")
    # Native ONNX runtimes must not change the other tests' CUDA selection state.
    result = subprocess.run(
        [sys.executable, launcher.__file__, "--check-audio"],
        env=dict(os.environ, LOCALAPPDATA=str(tmp_path)), capture_output=True,
        text=True, timeout=30, check=False,
    )
    trace = tmp_path / "Greffier" / "demarrage.log"
    assert result.returncode == 0, result.stderr + (trace.read_text() if trace.exists() else "")


def test_an_audio_dependency_failure_returns_an_error_without_a_dialog(monkeypatch, tmp_path):
    trace = tmp_path / "audio-check.log"

    def broken_decoder():
        raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

    def unexpected_dialog(_message):
        pytest.fail("A headless audio check must not open a dialog")

    monkeypatch.setattr(launcher, "check_audio", broken_decoder)
    monkeypatch.setattr(launcher, "log", lambda: trace)
    monkeypatch.setattr(launcher, "_say_on_screen", unexpected_dialog)
    monkeypatch.setattr(sys, "argv", ["Greffier.exe", "--check-audio"])
    assert launcher.main() == 1
    assert "metadata_errors" in trace.read_text()


def test_the_audio_check_exits_without_starting_the_window(monkeypatch):
    called = []
    monkeypatch.setattr(launcher, "check_audio", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["Greffier.exe", "--check-audio"])
    FakeWindow.spun = False
    assert launcher.main() == 0
    assert called == [True]
    assert FakeWindow.spun is False


@pytest.mark.parametrize("workflow", ["release.yml", "windows-proof.yml"])
def test_the_windows_build_includes_the_speech_detector_model(workflow):
    text = (RACINE / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    assert "--collect-data faster_whisper" in text


def test_a_missing_bundled_speech_detector_fails_the_audio_check(monkeypatch, tmp_path):
    pytest.importorskip("faster_whisper")
    from faster_whisper import vad

    def missing_model(*_args, **_kwargs):
        raise FileNotFoundError("faster_whisper/assets/silero_vad_v6.onnx")

    trace = tmp_path / "missing-vad.log"
    monkeypatch.setattr(vad, "get_speech_timestamps", missing_model)
    monkeypatch.setattr(launcher, "log", lambda: trace)
    monkeypatch.setattr(sys, "argv", ["Greffier.exe", "--check-audio"])
    assert launcher.main() == 1
    assert "silero_vad_v6.onnx" in trace.read_text()
