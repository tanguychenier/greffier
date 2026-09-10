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
    effacees: tuple[str, ...] = ()
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
    quand: datetime | None = None,
) -> Made:
    """Writes the archive and applies the rotation."""
    name = BackupName(quand or datetime.now(UTC).astimezone())
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{name}.tar.gz"

    pris: list[str] = []
    files = 0
    temporary = archive.with_suffix(".partiel")
    try:
        with tarfile.open(temporary, "w:gz") as tar:
            for folder in CONTENT:
                source = data / folder
                if not source.exists():
                    continue
                tar.add(source, arcname=folder)
                pris.append(folder)
                files += sum(1 for _ in source.rglob("*") if _.is_file())
            if config is not None and config.exists():
                for file in ("config.toml", "contexte.toml", "sujets.toml"):
                    path = config / file
                    if path.exists():
                        tar.add(path, arcname=f"configuration/{file}")
                        files += 1
                pris.append("configuration")
        temporary.replace(archive)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    effacees: list[str] = []
    for vieille in to_erase(
        [path.name.removesuffix(".tar.gz")
         for path in destination.glob("greffier-*.tar.gz")],
        kept,
    ):
        path = destination / f"{vieille}.tar.gz"
        try:
            path.unlink()
            effacees.append(vieille)
        except OSError:
            continue

    return Made(archive, tuple(pris), files,
                 archive.stat().st_size, tuple(effacees), data=data)

def restore(archive: Path, data: Path, ecraser: bool = False) -> list[str]:
    """Puts a backup back. Returns the folders restored."""
    if not archive.exists():
        raise FileNotFoundError(f"archive introuvable : {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        racines = sorted({
            membre.name.split("/")[0] for membre in tar.getmembers()
            if "/" in membre.name or membre.isdir()
        })
        if not ecraser:
            deja = [name for name in racines if (data / name).exists()]
            if deja:
                raise FileExistsError(
                    "déjà présent, et rien n'a été touché : "
                    + ", ".join(deja)
                    + ". Relance en demandant explicitement d'écraser."
                )
        data.mkdir(parents=True, exist_ok=True)
        tar.extractall(data, filter="data")
    return racines

def lister(destination: Path) -> list[tuple[str, int, datetime]]:
    """The backups present, most recent first."""
    trouvees: list[tuple[str, int, datetime]] = []
    if not destination.exists():
        return trouvees
    for path in destination.glob("greffier-*.tar.gz"):
        quand = BackupName.read(path.name.removesuffix(".tar.gz"))
        if quand is None:
            continue
        trouvees.append((path.name, path.stat().st_size, quand))
    return sorted(trouvees, key=lambda line: line[2], reverse=True)

def space_available(destination: Path) -> int:
    """Free bytes where writing happens. Zero when unknown."""
    try:
        return shutil.disk_usage(destination).free
    except OSError:
        return 0
