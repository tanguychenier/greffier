"""The interpreter check on a macOS bundle, the guard the launchers of 0.3.33 lacked."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import check_bundle_scripts as check  # noqa: E402

# The first line of greffier's launcher in the published Intel bundle.
WORKSHOP = ("/var/folders/20/jp1_0n3n7kndh6rnbqb5344m0000gn/T/greffier-paquet.9BU6Lc"
            "/Greffier.app/Contents/MacOS/Greffier")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="no executable bit on Windows; the bundle is macOS's"
)


def lay(folder: Path, name: str, text: str, executable: bool = True) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755 if executable else 0o644)
    return path


class TestTheFirstLine:
    @pytest.mark.parametrize(("head", "named"), [
        (f"#!{WORKSHOP}\n# -*- coding: utf-8 -*-\n".encode(), WORKSHOP),
        (b"#!/bin/sh\nexec true\n", "/bin/sh"),
        (b"#! /usr/bin/env python3\n", "/usr/bin/env"),
        (b"#!/usr/bin/env -S python3 -u\n", "/usr/bin/env"),
        (b"#!/bin/sh", "/bin/sh"),
        (b"#! \n", ""),
    ])
    def test_the_interpreter_is_its_first_word(self, head, named):
        assert check.interpreter(head) == named

    @pytest.mark.parametrize("head", [
        b"", b"import sys\n", b"\xcf\xfa\xed\xfe\x07", b" #!/bin/sh\n", b"# a comment\n",
    ])
    def test_without_a_shebang_there_is_none(self, head):
        assert check.interpreter(head) is None

    def test_an_empty_shebang_names_nothing_rather_than_passing(self):
        assert check.interpreter(b"#!\n") == ""
        assert not check.portable("")

    def test_only_the_system_folders_are_on_every_mac(self):
        assert check.portable("/bin/sh")
        assert check.portable("/usr/bin/env")
        assert not check.portable(WORKSHOP)
        assert not check.portable("/usr/local/bin/python3")
        assert not check.portable("/opt/homebrew/bin/python3")
        assert not check.portable("python3")
        # A prefix of the folder's name is not the folder.
        assert not check.portable("/binaries/sh")
        assert not check.portable("/usr/binx/env")


class TestABundle:
    def test_a_launcher_naming_the_workshop_is_found(self, tmp_path):
        launcher = lay(tmp_path, "Contents/bin/greffier", f"#!{WORKSHOP}\nimport sys\n")
        assert list(check.dangling(tmp_path)) == [(launcher, WORKSHOP)]

    def test_system_interpreters_pass(self, tmp_path):
        lay(tmp_path, "Contents/Resources/run.sh", "#!/bin/sh\nexec true\n")
        lay(tmp_path, "Contents/lib/tool.py", "#!/usr/bin/env python3\n")
        assert list(check.dangling(tmp_path)) == []

    def test_a_module_that_is_never_run_says_nothing(self, tmp_path):
        """Library sources carry shebangs to /usr/local and the like; they are imported."""
        lay(tmp_path, "Contents/lib/module.py", "#!/usr/local/bin/python\n", executable=False)
        assert list(check.dangling(tmp_path)) == []

    # Owner, group, others: each bit alone.
    @pytest.mark.parametrize("mode", [0o744, 0o654, 0o645])
    def test_any_executable_bit_makes_it_a_script(self, tmp_path, mode):
        script = lay(tmp_path, "run", "#!/opt/python\n")
        script.chmod(mode)
        assert list(check.dangling(tmp_path)) == [(script, "/opt/python")]

    def test_a_binary_is_not_a_script(self, tmp_path):
        """The bundle's own executable is a Mach-O file, with no first line to read."""
        binary = tmp_path / "Contents/MacOS/Greffier"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\xcf\xfa\xed\xfe\x07\x00\x00\x01")
        binary.chmod(0o755)
        assert list(check.dangling(tmp_path)) == []

    def test_links_are_not_followed(self, tmp_path):
        """A link points inside the bundle, where its target is read anyway."""
        target = lay(tmp_path, "real", "#!/opt/python\n")
        (tmp_path / "link").symlink_to(target)
        assert [path for path, _ in check.dangling(tmp_path)] == [target]

    def test_every_one_is_named_in_order(self, tmp_path, monkeypatch):
        """Whatever order the file system lists them in: two runs read alike."""
        first = lay(tmp_path, "a/f2py", f"#!{WORKSHOP}\n")
        second = lay(tmp_path, "b/tqdm", f"#!{WORKSHOP}\n")
        listed = Path.rglob
        monkeypatch.setattr(Path, "rglob", lambda self, pattern: reversed(
            list(listed(self, pattern))))
        assert [path for path, _ in check.dangling(tmp_path)] == [first, second]


class TestTheCommand:
    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RACINE / "tools/check_bundle_scripts.py"), *arguments],
            capture_output=True, text=True, check=False,
        )

    def test_a_dangling_launcher_fails_the_release(self, tmp_path):
        bundle = tmp_path / "Greffier.app"
        lay(bundle, "Contents/bin/greffier", f"#!{WORKSHOP}\n")
        done = self.run(str(bundle))
        assert done.returncode == 1
        assert f"greffier: runs through {WORKSHOP}, which is not on every Mac" in done.stdout
        assert done.stdout.startswith("::error::")

    def test_a_clean_bundle_passes(self, tmp_path):
        bundle = tmp_path / "Greffier.app"
        lay(bundle, "Contents/Resources/run.sh", "#!/bin/sh\n")
        done = self.run(str(bundle))
        assert done.returncode == 0, done.stdout
        assert "Every script of Greffier.app runs through" in done.stdout

    def test_an_empty_shebang_is_said_as_nothing(self, tmp_path):
        lay(tmp_path, "run", "#!\n")
        done = self.run(str(tmp_path))
        assert done.returncode == 1
        assert "runs through nothing" in done.stdout

    def test_a_missing_bundle_is_an_error_not_a_pass(self, tmp_path):
        done = self.run(str(tmp_path / "absent.app"))
        assert done.returncode == 1
        assert "no such bundle" in done.stdout
