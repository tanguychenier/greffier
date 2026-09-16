#!/usr/bin/env python3
"""Entry point of the packaged executables: the Windows one, the Linux AppImage.

PyInstaller needs a script to bundle, and `python -m greffier fenetre` is
not one. This file does nothing but what that command would do, with three
precautions an executable requires and the command line does not:

- **hand back on `--version`.** A graphical executable launched with no
  screen, a continuous integration runner for instance, cannot open a
  window. Answering its version is the only check possible there, and it is
  the one the release workflow runs.
- **write what breaks to a file.** A Windows graphical application has no
  console: an uncaught exception vanishes, and the user sees a window that
  does not open, with nothing to send to understand why.
- **say plainly what is missing.** ffmpeg absent from the PATH is the most
  likely case on a fresh machine, and « ModuleNotFoundError » tells nobody.

Opened on a Windows runner on 2026-09-15 (`windows-proof.yml`), never yet on
somebody's own machine. Wrapped into an AppImage by `tools/build_appimage.py`.
"""

from __future__ import annotations

import contextlib
import sys
import traceback
from pathlib import Path


def log() -> Path:
    """Where to write what breaks. `%LOCALAPPDATA%` on Windows, the data folder
    elsewhere, the same place as the rest of the tool's traces."""
    import os

    base = os.environ.get("LOCALAPPDATA")
    folder = Path(base) / "Greffier" if base else Path.home() / ".greffier"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "demarrage.log"


def version() -> str:
    from greffier.adapters.updates import installed_version

    return installed_version() or "inconnue"


def main() -> int:
    if "--version" in sys.argv:
        print(f"Greffier {version()}")
        return 0
    try:
        # Imported here and not at the top: on `--version`, loading the
        # interface would cost Tk and the models for a string.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window
        from greffier.locations import locate_tcl

        locate_tcl()
        Window(Config()).spin()
    except Exception:  # noqa: BLE001, dernier recours avant l'écran noir
        trace = traceback.format_exc()
        target = log()
        with contextlib.suppress(OSError):
            target.write_text(trace, encoding="utf-8")
        _say_on_screen(
            "Greffier n'a pas pu démarrer.\n\n"
            f"Le détail est dans :\n{target}\n\n"
            + _likely_cause(trace)
        )
        return 1
    return 0


def _likely_cause(trace: str) -> str:
    """What is missing, when the trace says it clearly.

    Two cases cover almost everything on a fresh machine, and neither can be
    guessed from reading a Python trace.
    """
    if "ffmpeg" in trace.lower():
        return ("ffmpeg est probablement absent. Installez-le, ou lancez "
                "l'installeur de Greffier.")
    if "Tcl" in trace or "tkinter" in trace:
        return "L'interface graphique n'a pas pu s'ouvrir (Tcl/Tk introuvable)."
    return ""


def _say_on_screen(message: str) -> None:
    """A dialog box, or the error output failing that.

    Failing that, because if Tk is precisely what is missing, a Tk dialog box
    will not show, and it is a likely case here.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Greffier", message)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
