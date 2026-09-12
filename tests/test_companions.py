"""The two processes a meeting runs alongside itself.

Started the same way from the window and from the command line -- and the window
used to reach into the command line's private functions to do it, which is two
primary adapters leaning on each other.
"""

from __future__ import annotations

import pytest

from greffier.adapters import companions


@pytest.fixture
def lancements(monkeypatch):
    lances: list[list[str]] = []
    monkeypatch.setattr(
        companions.subprocess, "Popen", lambda command, **k: lances.append(command))
    return lances


class TestTheLiveThread:
    def test_it_starts_when_the_settings_ask_for_it(self, lancements, tmp_path):
        assert companions.start_the_live_thread(tmp_path, active=True)
        assert lancements[0][-1] == "assister"

    def test_it_does_not_when_they_do_not(self, lancements, tmp_path):
        assert not companions.start_the_live_thread(tmp_path, active=False)
        assert lancements == []

    def test_the_settings_file_follows_it(self, lancements, tmp_path):
        """A meeting started with a chosen configuration keeps it in its helpers."""
        companions.start_the_live_thread(tmp_path, True, tmp_path / "config.toml")
        assert "--config" in lancements[0]

    def test_its_output_is_kept(self, lancements, tmp_path):
        """A helper that dies silently is a meeting with no live thread and no reason."""
        companions.start_the_live_thread(tmp_path, active=True)
        assert (tmp_path / "direct.log").exists()


class TestTheHardwareWatch:
    def test_it_is_macos_only(self, lancements, tmp_path, monkeypatch):
        """Elsewhere a device does not vanish from under a running recording."""
        monkeypatch.setattr(companions, "SYSTEM", "Linux")
        assert not companions.start_the_watch(tmp_path)
        assert lancements == []

    def test_there_it_starts(self, lancements, tmp_path, monkeypatch):
        monkeypatch.setattr(companions, "SYSTEM", "Darwin")
        assert companions.start_the_watch(tmp_path)
        assert lancements[0][-1] == "veiller"


class TestWhenItCannotStart:
    def test_a_refusal_is_reported_rather_than_raised(self, tmp_path, monkeypatch):
        """A meeting must start even where its helpers cannot."""
        def refuse(*a, **k):
            raise OSError("plus de processus")

        monkeypatch.setattr(companions.subprocess, "Popen", refuse)
        assert not companions.start_the_live_thread(tmp_path, active=True)
