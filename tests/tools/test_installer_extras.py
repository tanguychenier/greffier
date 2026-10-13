"""Installation requests must match the package published from this tree."""

from __future__ import annotations

import importlib.util
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("with_uv", [True, False])
@pytest.mark.parametrize(("engine", "with_cuda"), [
    ("whisper.cpp", False), ("faster-whisper", False), ("faster-whisper", True),
])
def test_installation_never_requests_an_undeclared_extra(
    tmp_path, monkeypatch, with_uv, engine, with_cuda,
):
    specification = importlib.util.spec_from_file_location("installer", ROOT / "tools/install.py")
    installer = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(installer)
    declarations = tomllib.loads((ROOT / "pyproject.toml").read_text())
    declared = set(declarations["project"]["optional-dependencies"])
    environment = tmp_path / ".venv/bin"
    environment.mkdir(parents=True)
    (environment / "python").touch()
    monkeypatch.setattr(installer, "ROOT", tmp_path)
    monkeypatch.setattr(installer, "nvidia_card", lambda: with_cuda)
    monkeypatch.setattr(installer, "card_step", lambda *_: None)
    monkeypatch.setattr(
        installer.shutil, "which",
        lambda name: "/usr/bin/uv" if name == "uv" and with_uv else None,
    )
    commands = []

    def run(command, **_):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(installer, "run_job", run)
    context = type("Context", (), {
        "check_only": False, "to_do": [], "ask": lambda *_: with_cuda,
    })()
    installer.environment_step(context, engine)
    requests = [command[-1] for command in commands if "install" in command]
    assert len(requests) == 1
    package = requests[0]
    extras = set(package[2:-1].split(",")) if package.startswith(".[") else set()
    assert extras <= declared
    assert ("transcription" in extras) == (engine == "faster-whisper")
    assert ("cuda" in extras) == with_cuda
    assert "dev" not in extras
