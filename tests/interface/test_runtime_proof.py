"""A packaged runtime reports its own tabs without inspecting the desktop."""

from __future__ import annotations

import json
import time

import pytest

from greffier.adapters.configuration import Config
from greffier.interface.runtime_proof import schedule
from greffier.interface.window import Window


@pytest.mark.usefixtures("test_screen")
def test_the_real_window_reports_every_tab_at_both_widths(tmp_path):
    window = Window(Config())
    proof = schedule(window, tmp_path, interval_ms=1)
    deadline = time.monotonic() + 10
    while not proof.finished and time.monotonic() < deadline:
        window.root.update()
    assert proof.finished
    result = json.loads((tmp_path / "runtime-proof.json").read_text())
    assert result["ok"], result["errors"]
    assert result["pixels_captured"] is False
    assert len(result["visits"]) == len(window.tabs._pages) * 2
    assert {v["width"] for v in result["visits"]} == {880, 1280}


def test_a_proof_requires_an_explicit_test_environment(window, tmp_path, monkeypatch):
    monkeypatch.delenv("GREFFIER_ECRAN_D_ESSAI", raising=False)
    with pytest.raises(ValueError, match="environnement d'essai"):
        schedule(window, tmp_path)
