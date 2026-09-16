"""Which identity the macOS bundle is signed with, and what must never happen.

Creating a local certificate asks the keychain to trust it, and macOS opens a
password window for that. With nobody in front of the screen the window waits
for ever: the continuous integration runner sat there for over an hour, the job
was cancelled, and the release never received its macOS bundle.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "macos" / "identite-de-signature.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not SCRIPT.exists(),
    reason="le script de signature ne sert que sur macOS",
)


@pytest.fixture
def without_identity(tmp_path):
    """A PATH where `security` answers that no identity exists."""
    wrong = tmp_path / "bin"
    wrong.mkdir()
    (wrong / "security").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (wrong / "security").chmod(0o755)
    for tool in ("openssl", "mktemp", "grep", "head", "tr", "rm", "cat", "echo"):
        true_ = shutil.which(tool)
        if true_:
            (wrong / tool).symlink_to(true_)
    return wrong


def lancer(bin_path, **environment_):
    milieu = dict(os.environ, PATH=f"{bin_path}:/usr/bin:/bin", **environment_)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True,
        timeout=30, check=False, env=milieu, cwd=RACINE,
    )


class TestNothingEverWaitsForAPassword:
    def test_a_runner_falls_back_to_ad_hoc(self, without_identity):
        """`CI` is set by every runner. No certificate is created there."""
        finished = lancer(without_identity, CI="true")
        assert finished.stdout.strip() == "-"
        assert "ad hoc" in finished.stderr

    def test_it_says_why_rather_than_failing_silently(self, without_identity):
        assert "non interactive" in lancer(without_identity, CI="true").stderr

    def test_it_returns_at_once(self, without_identity):
        """The whole point: it must not hang. Thirty seconds is already ten
        times what it needs."""
        finished = lancer(without_identity, CI="true")
        assert finished.returncode == 0


class TestWhatIsAskedForIsWhatIsUsed:
    def test_an_explicit_choice_wins_over_everything(self, without_identity):
        finished = lancer(without_identity, GREFFIER_SIGNATURE="Developer ID Application: X")
        assert finished.stdout.strip() == "Developer ID Application: X"

    def test_ad_hoc_can_be_asked_for_by_name(self, without_identity):
        assert lancer(without_identity, GREFFIER_SIGNATURE="-").stdout.strip() == "-"
