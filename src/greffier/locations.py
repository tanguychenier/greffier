"""Where the tool files its configuration and its data, per system.

A module with no dependency: the installer reads it before pydantic exists, and
has to say the same thing as the rest.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import sys
from pathlib import Path

NATIF_MACOS = "Library/Application Support/Greffier"
FICHIERS_CONFIG = ("config.toml", ".env")

def _system(system: str | None) -> str:
    return system or platform.system()

def former_config_folder() -> Path:
    return Path.home() / ".config/greffier"

def former_data_folder() -> Path:
    return Path.home() / ".local/share/greffier"

def config_folder(system: str | None = None) -> Path:
    system = _system(system)
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "greffier"
    if system == "Darwin" and "XDG_CONFIG_HOME" not in os.environ:
        natif = Path.home() / NATIF_MACOS
        former = former_config_folder()
        if not _holds_configuration(natif) and _holds_configuration(former):
            return former
        return natif
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "greffier"

def data_folder(system: str | None = None) -> Path:
    system = _system(system)
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "greffier"
    if system == "Darwin" and "XDG_DATA_HOME" not in os.environ:
        natif = Path.home() / NATIF_MACOS
        former = former_data_folder()
        if not natif.exists() and former.exists():
            return former
        return natif
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "greffier"

def _holds_configuration(folder: Path) -> bool:
    return any((folder / name).exists() for name in FICHIERS_CONFIG)

def relocate(system: str | None = None) -> list[tuple[Path, Path]]:
    """Brings out of hidden folders what an earlier version put there."""
    if _system(system) != "Darwin":
        return []
    natif = Path.home() / NATIF_MACOS
    faits: list[tuple[Path, Path]] = []
    if "XDG_DATA_HOME" not in os.environ:
        faits += _move_contents(former_data_folder(), natif)
    if "XDG_CONFIG_HOME" not in os.environ:
        faits += _move_contents(former_config_folder(), natif)
    return faits

def _move_contents(former: Path, natif: Path) -> list[tuple[Path, Path]]:
    if not former.is_dir():
        return []
    natif.mkdir(parents=True, exist_ok=True)
    faits = []
    for source in sorted(former.iterdir()):
        target = natif / source.name
        if target.exists() or target.is_symlink():
            continue
        shutil.move(str(source), str(target))
        faits.append((source, target))
    with contextlib.suppress(OSError):
        former.rmdir()
    return faits

def locate_tcl(environnement: dict[str, str] | None = None, prefixe: Path | None = None) -> None:
    """Tells Tcl where its files are, when the interpreter cannot find them."""
    env = environnement if environnement is not None else os.environ
    root = prefixe or Path(sys.base_prefix)
    for variable, motif in (("TCL_LIBRARY", "tcl"), ("TK_LIBRARY", "tk")):
        if env.get(variable):
            continue
        candidats = sorted((root / "lib").glob(f"{motif}[0-9]*.[0-9]*"))
        dossiers = [c for c in candidats if c.is_dir()]
        if dossiers:
            env[variable] = str(dossiers[-1])
