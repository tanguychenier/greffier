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
def sans_identite(tmp_path):
    """A PATH where `security` answers that no identity exists."""
    faux = tmp_path / "bin"
    faux.mkdir()
    (faux / "security").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (faux / "security").chmod(0o755)
    for outil in ("openssl", "mktemp", "grep", "head", "tr", "rm", "cat", "echo"):
        vrai = shutil.which(outil)
        if vrai:
            (faux / outil).symlink_to(vrai)
    return faux


def lancer(chemin_bin, **environnement):
    milieu = dict(os.environ, PATH=f"{chemin_bin}:/usr/bin:/bin", **environnement)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True,
        timeout=30, check=False, env=milieu, cwd=RACINE,
    )


class TestNothingEverWaitsForAPassword:
    def test_a_runner_falls_back_to_ad_hoc(self, sans_identite):
        """`CI` is set by every runner. No certificate is created there."""
        fini = lancer(sans_identite, CI="true")
        assert fini.stdout.strip() == "-"
        assert "ad hoc" in fini.stderr

    def test_it_says_why_rather_than_failing_silently(self, sans_identite):
        assert "non interactive" in lancer(sans_identite, CI="true").stderr

    def test_it_returns_at_once(self, sans_identite):
        """The whole point: it must not hang. Thirty seconds is already ten
        times what it needs."""
        fini = lancer(sans_identite, CI="true")
        assert fini.returncode == 0


class TestWhatIsAskedForIsWhatIsUsed:
    def test_an_explicit_choice_wins_over_everything(self, sans_identite):
        fini = lancer(sans_identite, GREFFIER_SIGNATURE="Developer ID Application: X")
        assert fini.stdout.strip() == "Developer ID Application: X"

    def test_ad_hoc_can_be_asked_for_by_name(self, sans_identite):
        assert lancer(sans_identite, GREFFIER_SIGNATURE="-").stdout.strip() == "-"
