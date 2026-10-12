"""The two processes a meeting runs alongside itself.

Started the same way from the window and from the command line -- and the window
used to reach into the command line's private functions to do it, which is two
primary adapters leaning on each other.
"""

from __future__ import annotations

import gc
import sys
import time
import weakref
from types import SimpleNamespace

import pytest

from greffier.adapters import companions


@pytest.fixture
def launches(monkeypatch):
    lances: list[list[str]] = []
    monkeypatch.setattr(
        companions.subprocess, "Popen",
        lambda command, **_k: (lances.append(command), SimpleNamespace(wait=lambda: 0))[1],
    )
    return lances


class TestTheLiveThread:
    def test_it_starts_when_the_settings_ask_for_it(self, launches, tmp_path):
        assert companions.start_the_live_thread(tmp_path, active=True)
        assert launches[0][-1] == "assister"

    def test_it_does_not_when_they_do_not(self, launches, tmp_path):
        assert not companions.start_the_live_thread(tmp_path, active=False)
        assert launches == []

    def test_the_settings_file_follows_it(self, launches, tmp_path):
        """A meeting started with a chosen configuration keeps it in its helpers."""
        companions.start_the_live_thread(tmp_path, True, tmp_path / "config.toml")
        assert "--config" in launches[0]

    @pytest.mark.usefixtures("launches")
    def test_its_output_is_kept(self, tmp_path):
        """A helper that dies silently is a meeting with no live thread and no reason."""
        companions.start_the_live_thread(tmp_path, active=True)
        assert (tmp_path / "direct.log").exists()


class TestTheHardwareWatch:
    def test_it_is_macos_only(self, launches, tmp_path, monkeypatch):
        """Elsewhere a device does not vanish from under a running recording."""
        monkeypatch.setattr(companions, "SYSTEM", "Linux")
        assert not companions.start_the_watch(tmp_path)
        assert launches == []

    def test_there_it_starts(self, launches, tmp_path, monkeypatch):
        monkeypatch.setattr(companions, "SYSTEM", "Darwin")
        assert companions.start_the_watch(tmp_path)
        assert launches[0][-1] == "veiller"


class TestWhenItCannotStart:
    def test_a_refusal_is_reported_rather_than_raised(self, tmp_path, monkeypatch):
        """A meeting must start even where its helpers cannot."""
        def refuse(*_a, **_k):
            raise OSError("plus de processus")

        monkeypatch.setattr(companions.subprocess, "Popen", refuse)
        assert not companions.start_the_live_thread(tmp_path, active=True)


def test_a_live_helper_is_kept_until_its_exit_and_reaped(tmp_path, monkeypatch):
    real_popen = companions.subprocess.Popen
    references = []

    def start(command, **options):
        process = real_popen(command, **options)
        references.append(weakref.ref(process))
        return process

    monkeypatch.setattr(companions.subprocess, "Popen", start)
    gate = tmp_path / "finish"
    script = (
        "import sys,time; from pathlib import Path; gate=Path(sys.argv[1])\n"
        "while not gate.exists(): time.sleep(0.01)\n"
    )
    try:
        assert companions._launch([sys.executable, "-c", script, str(gate)], tmp_path / "log")
        gc.collect()
        assert references[0]() is not None
    finally:
        gate.touch()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        process = references[0]()
        if process is None or process.returncode is not None:
            break
        time.sleep(0.01)
    assert process is None or process.returncode == 0
