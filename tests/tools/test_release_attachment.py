"""Run the release action through its creation race without contacting GitHub."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ["RELEASE_TEST_ROOT"])
mode = os.environ["RELEASE_TEST_CASE"]
operation = sys.argv[2]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(operation) + "\\n")
created = root / "created"
if operation == "view":
    raise SystemExit(0 if created.exists() else 1)
if operation == "create":
    if mode == "denied":
        raise SystemExit(1)
    created.touch()
    raise SystemExit(1 if mode == "race" else 0)
if operation == "upload":
    raise SystemExit(3 if mode == "upload_denied" else 0)
raise SystemExit(4)
'''


@pytest.mark.parametrize(
    ("case", "expected", "operations"),
    [
        ("existing", 0, ["view", "upload"]),
        ("new", 0, ["view", "create", "upload"]),
        ("race", 0, ["view", "create", "view", "upload"]),
        ("denied", 1, ["view", "create", "view"]),
        ("upload_denied", 3, ["view", "upload"]),
    ],
)
def test_creation_is_recoverable_only_when_another_job_created_the_release(
    tmp_path, case, expected, operations,
):
    binary = tmp_path / "gh"
    binary.write_text(FAKE_GH)
    binary.chmod(0o700)
    if case in ("existing", "upload_denied"):
        (tmp_path / "created").touch()
    action = (ROOT / ".github/actions/attach-to-release/action.yml").read_text()
    script = textwrap.dedent(action.split("      run: |\n", 1)[1])
    script = script.replace("${{ inputs.file }}", "distribution.zip")
    environment = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
                       RELEASE_TEST_ROOT=str(tmp_path), RELEASE_TEST_CASE=case,
                       GITHUB_REF_NAME="v99.0.0-test", GITHUB_REPOSITORY="example/test")
    finished = subprocess.run(["bash", "-e", "-c", script], env=environment,
                              capture_output=True, text=True, timeout=20, check=False)
    assert finished.returncode == expected, finished.stderr
    called = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert called == operations
