"""Files that hold a secret: the owner's alone from the first byte, whole at every instant."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from greffier.adapters import private_files
from greffier.adapters.private_files import write_private_text

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are a posix thing")


@pytest.fixture
def permissive_umask() -> Iterator[None]:
    """The usual desktop umask, under which a plain `write_text` gives 0644."""
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestTheFileIsTheOwnerSAlone:
    @posix_only
    def test_whatever_the_umask_says(self, tmp_path: Path, permissive_umask: None) -> None:
        target = tmp_path / "jetons.toml"
        write_private_text(target, "secret")
        assert mode_of(target) == 0o600

    @posix_only
    def test_already_before_it_takes_the_target_s_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permissive_umask: None
    ) -> None:
        """The old writer left a 0644 file for the time of the write; the temporary
        is private before a single byte goes into it, so no instant is exposed."""
        seen: list[int] = []
        replace = os.replace

        def look_then_replace(source: str, destination: Path) -> None:
            seen.append(mode_of(Path(source)))
            replace(source, destination)

        monkeypatch.setattr(private_files.os, "replace", look_then_replace)
        write_private_text(tmp_path / "jetons.toml", "secret")
        assert seen == [0o600]

    @posix_only
    def test_a_file_readable_by_all_becomes_private_on_the_next_write(
        self, tmp_path: Path, permissive_umask: None
    ) -> None:
        """What an earlier version left at 0644 is repaired the first time it is rewritten."""
        target = tmp_path / "jetons.toml"
        target.write_text("ancien", encoding="utf-8")
        target.chmod(0o644)
        write_private_text(target, "nouveau")
        assert mode_of(target) == 0o600

    @posix_only
    def test_a_missing_folder_is_created_for_the_owner_alone(
        self, tmp_path: Path, permissive_umask: None
    ) -> None:
        target = tmp_path / "greffier" / "jetons.toml"
        write_private_text(target, "secret")
        assert mode_of(target.parent) == 0o700

    @posix_only
    def test_a_folder_that_exists_keeps_its_mode(
        self, tmp_path: Path, permissive_umask: None
    ) -> None:
        """The data folder is shared with the meetings: it is not ours to lock."""
        folder = tmp_path / "donnees"
        folder.mkdir(mode=0o755)
        write_private_text(folder / "outils.json", "{}")
        assert mode_of(folder) == 0o755


class TestTheContent:
    def test_non_ascii_text_reads_back_as_written(self, tmp_path: Path) -> None:
        target = tmp_path / "jetons.toml"
        text = "clé « très » secrète — 日本語 🔑\n"
        write_private_text(target, text)
        assert target.read_text(encoding="utf-8") == text

    def test_a_shorter_text_replaces_the_longer_one_whole(self, tmp_path: Path) -> None:
        """A rewrite in place would leave the tail of the old content behind."""
        target = tmp_path / "jetons.toml"
        write_private_text(target, "un contenu assez long")
        write_private_text(target, "court")
        assert target.read_text(encoding="utf-8") == "court"

    def test_no_temporary_remains_once_written(self, tmp_path: Path) -> None:
        write_private_text(tmp_path / "jetons.toml", "secret")
        assert [p.name for p in tmp_path.iterdir()] == ["jetons.toml"]


class TestWhenTheWriteFails:
    def test_the_previous_content_stays_whole_and_nothing_else_remains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "jetons.toml"
        write_private_text(target, "avant")

        def refuse(_source: str, _destination: Path) -> None:
            raise OSError("disque plein")

        monkeypatch.setattr(private_files.os, "replace", refuse)
        with pytest.raises(OSError, match="disque plein"):
            write_private_text(target, "après")
        assert target.read_text(encoding="utf-8") == "avant"
        assert [p.name for p in tmp_path.iterdir()] == ["jetons.toml"]

    @posix_only
    def test_a_refused_chmod_closes_the_descriptor_and_leaves_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fchmod used to run before the stream took the descriptor over: when it
        failed, the temporary was removed but the descriptor stayed open."""
        descriptors: list[int] = []
        mkstemp = tempfile.mkstemp

        def remember_then_open(**arguments: Any) -> tuple[int, str]:
            descriptor, temporary = mkstemp(**arguments)
            descriptors.append(descriptor)
            return descriptor, temporary

        def refuse(_descriptor: int, _mode: int) -> None:
            raise OSError("chmod refusé")

        monkeypatch.setattr(private_files.tempfile, "mkstemp", remember_then_open)
        monkeypatch.setattr(private_files.os, "fchmod", refuse)
        with pytest.raises(OSError, match="chmod refusé"):
            write_private_text(tmp_path / "jetons.toml", "secret")
        assert len(descriptors) == 1
        with pytest.raises(OSError):
            os.fstat(descriptors[0])
        assert list(tmp_path.iterdir()) == []
