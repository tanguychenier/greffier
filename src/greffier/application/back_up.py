"""Making a backup, and knowing how to restore it."""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.backup import CONTENT, KEPT, BackupName, to_erase


@dataclass(frozen=True, slots=True)
class Made:
    """What a backup carried away."""

    archive: Path
    dossiers: tuple[str, ...]
    files: int
    bytes_read: int
    erased: tuple[str, ...] = ()
    data: Path | None = None

    @property
    def on_the_same_disk(self) -> bool:
        """True when the archive stayed under what it backs up.

        Which protects against a mistake but not against losing the disk, and that is
        worth saying rather than hiding.
        """
        if self.data is None:
            return False
        try:
            self.archive.parent.resolve().relative_to(self.data.resolve())
        except (ValueError, OSError):
            return False
        return True

def do_it(
    data: Path,
    config: Path | None,
    destination: Path,
    kept: int = KEPT,
    when: datetime | None = None,
) -> Made:
    """Writes the archive and applies the rotation."""
    name = BackupName(when or datetime.now(UTC).astimezone())
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{name}.tar.gz"

    taken: list[str] = []
    files = 0
    temporary = archive.with_suffix(".partiel")
    try:
        with tarfile.open(temporary, "w:gz") as tar:
            for folder in CONTENT:
                source = data / folder
                if not source.exists():
                    continue
                tar.add(source, arcname=folder)
                taken.append(folder)
                files += sum(1 for _ in source.rglob("*") if _.is_file())
            if config is not None and config.exists():
                for file in ("config.toml", "contexte.toml", "sujets.toml"):
                    path = config / file
                    if path.exists():
                        tar.add(path, arcname=f"configuration/{file}")
                        files += 1
                taken.append("configuration")
        temporary.replace(archive)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    erased: list[str] = []
    for old_one in to_erase(
        [path.name.removesuffix(".tar.gz")
         for path in destination.glob("greffier-*.tar.gz")],
        kept,
    ):
        path = destination / f"{old_one}.tar.gz"
        try:
            path.unlink()
            erased.append(old_one)
        except OSError:
            continue

    return Made(archive, tuple(taken), files,
                 archive.stat().st_size, tuple(erased), data=data)

def restore(archive: Path, data: Path, overwrite: bool = False) -> list[str]:
    """Puts a backup back. Returns the folders restored."""
    if not archive.exists():
        raise FileNotFoundError(f"archive introuvable : {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        roots = sorted({
            member.name.split("/")[0] for member in tar.getmembers()
            if "/" in member.name or member.isdir()
        })
        if not overwrite:
            already = [name for name in roots if (data / name).exists()]
            if already:
                raise FileExistsError(
                    "déjà présent, et rien n'a été touché : "
                    + ", ".join(already)
                    + ". Relance en demandant explicitement d'écraser."
                )
        data.mkdir(parents=True, exist_ok=True)
        tar.extractall(data, filter="data")
    return roots

def list_(destination: Path) -> list[tuple[str, int, datetime]]:
    """The backups present, most recent first."""
    found: list[tuple[str, int, datetime]] = []
    if not destination.exists():
        return found
    for path in destination.glob("greffier-*.tar.gz"):
        when = BackupName.read(path.name.removesuffix(".tar.gz"))
        if when is None:
            continue
        found.append((path.name, path.stat().st_size, when))
    return sorted(found, key=lambda line: line[2], reverse=True)

def space_available(destination: Path) -> int:
    """Free bytes where writing happens. Zero when unknown."""
    try:
        return shutil.disk_usage(destination).free
    except OSError:
        return 0
