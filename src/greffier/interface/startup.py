"""Makes Tkinter usable before anything imports it.

Standalone Python distributions, the ones `uv` and `pyenv` install and the one
a frozen bundle carries, ship `_tkinter` compiled and the Tcl library files,
but not where Tcl looks for them: it tries the build path of the machine that
compiled the interpreter.

    Cannot find a usable init.tcl in the following directories:
        /tools/deps/lib/tcl9.0 …

The files are two directories away. They are found here, and `TCL_LIBRARY` and
`TK_LIBRARY` are set, which has to happen **before** the first import of
`tkinter`: Tcl reads them once, at initialisation, and never again.

Nothing is overwritten: an environment that already sets them knows better
than we do.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _racines(prefixe: Path) -> list[Path]:
    """Where to look, most likely first."""
    return [prefixe / "lib", prefixe / "share", prefixe]

def _find(motif: str, prefixes: list[Path]) -> Path | None:
    for prefixe in prefixes:
        for root in _racines(prefixe):
            if not root.is_dir():
                continue
            for folder in sorted(root.glob(motif), reverse=True):
                if (folder / "init.tcl").exists() or motif.startswith("tk"):
                    return folder
    return None

def preparer() -> dict[str, str]:
    """Fills in the missing Tcl/Tk paths."""
    prefixes = [Path(sys.base_prefix), Path(sys.prefix)]
    pose: dict[str, str] = {}
    for variable, motif in (("TCL_LIBRARY", "tcl[0-9]*"), ("TK_LIBRARY", "tk[0-9]*")):
        if os.environ.get(variable):
            continue
        found = _find(motif, prefixes)
        if found is not None:
            os.environ[variable] = str(found)
            pose[variable] = str(found)
    return pose

def available() -> tuple[bool, str]:
    """Says whether a window can open, and why not when it cannot.

    **Nothing is instantiated.** Creating a Tk root to try it, destroying it, then
    creating a second one for the real window brings the process down with a
    segmentation fault on macOS with Tk 9. So this only checks that the module
    loads and that the Tcl files were found.
    """
    pose = preparer()
    try:
        import tkinter
    except ImportError:
        return False, (
            "Tkinter n'est pas installé avec ce Python. "
            "Sur Debian ou Ubuntu : « apt install python3-tk ». "
            "Sur macOS avec Homebrew : « brew install python-tk »."
        )
    if not os.environ.get("TCL_LIBRARY") and not _default_tcl():
        return False, (
            "les fichiers de bibliothèque Tcl sont introuvables. "
            "Renseigne TCL_LIBRARY, ou installe Tcl/Tk pour ce Python."
        )
    found = " (chemins Tcl résolus)" if pose else ""
    return True, f"Tkinter {tkinter.TkVersion}{found}"

def _default_tcl() -> bool:
    """True when Tcl will find its files without help.

    That is the case for a Python shipped by a distribution or by Homebrew, where
    Tcl is installed where it expects to be.
    """
    return any(
        (root / "init.tcl").exists()
        for prefixe in (Path(sys.base_prefix), Path("/usr"), Path("/opt/homebrew"))
        for root in prefixe.glob("lib/tcl*")
    )
