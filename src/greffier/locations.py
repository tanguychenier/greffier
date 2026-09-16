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

NATIVE_MACOS = "Library/Application Support/Greffier"
CONFIG_FILES = ("config.toml", ".env")

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
        native = Path.home() / NATIVE_MACOS
        former = former_config_folder()
        if not _holds_configuration(native) and _holds_configuration(former):
            return former
        return native
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "greffier"

def data_folder(system: str | None = None) -> Path:
    system = _system(system)
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "greffier"
    if system == "Darwin" and "XDG_DATA_HOME" not in os.environ:
        native = Path.home() / NATIVE_MACOS
        former = former_data_folder()
        if not native.exists() and former.exists():
            return former
        return native
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "greffier"

def _holds_configuration(folder: Path) -> bool:
    return any((folder / name).exists() for name in CONFIG_FILES)

def relocate(system: str | None = None) -> list[tuple[Path, Path]]:
    """Brings out of hidden folders what an earlier version put there."""
    if _system(system) != "Darwin":
        return []
    native = Path.home() / NATIVE_MACOS
    done_ones: list[tuple[Path, Path]] = []
    if "XDG_DATA_HOME" not in os.environ:
        done_ones += _move_contents(former_data_folder(), native)
    if "XDG_CONFIG_HOME" not in os.environ:
        done_ones += _move_contents(former_config_folder(), native)
    return done_ones

def _move_contents(former: Path, native: Path) -> list[tuple[Path, Path]]:
    if not former.is_dir():
        return []
    native.mkdir(parents=True, exist_ok=True)
    done_ones = []
    for source in sorted(former.iterdir()):
        target = native / source.name
        if target.exists() or target.is_symlink():
            continue
        shutil.move(str(source), str(target))
        done_ones.append((source, target))
    with contextlib.suppress(OSError):
        former.rmdir()
    return done_ones

def locate_tcl(environment_: dict[str, str] | None = None, the_prefix: Path | None = None) -> None:
    """Tells Tcl where its files are, when the interpreter cannot find them."""
    env = environment_ if environment_ is not None else os.environ
    root = the_prefix or Path(sys.base_prefix)
    for variable, motif in (("TCL_LIBRARY", "tcl"), ("TK_LIBRARY", "tk")):
        if env.get(variable):
            continue
        candidates_ = sorted((root / "lib").glob(f"{motif}[0-9]*.[0-9]*"))
        dossiers = [c for c in candidates_ if c.is_dir()]
        if dossiers:
            env[variable] = str(dossiers[-1])
