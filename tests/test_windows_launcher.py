"""The Windows launcher does what `greffier fenetre` does, and nothing it cannot do.

Never run on a real Windows as these tests are written; what a runner showed
on 2026-09-15 is that the launcher called a method the window no longer had,
and that the executable had no sentences to show. Neither survives here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import windows_launcher  # noqa: E402


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
        monkeypatch.setattr(windows_launcher, "log", lambda: tmp_path / "demarrage.log")
        monkeypatch.setattr(sys, "argv", ["Greffier.exe"])
        FakeWindow.spun = False
        assert windows_launcher.main() == 0
        assert FakeWindow.spun
        assert not (tmp_path / "demarrage.log").exists()

    def test_the_method_it_calls_exists_on_the_real_window(self):
        from greffier.interface.window import Window

        assert callable(getattr(Window, "spin", None))

    def test_version_answers_without_opening_anything(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["Greffier.exe", "--version"])
        assert windows_launcher.main() == 0
        assert capsys.readouterr().out.startswith("Greffier ")


class TestWhatTheExecutableCarries:
    @pytest.mark.parametrize("workflow", ["release.yml", "windows-proof.yml"])
    def test_the_sentences_and_the_sounds_travel_with_the_executable(self, workflow):
        text = (RACINE / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "--collect-data greffier" in text
