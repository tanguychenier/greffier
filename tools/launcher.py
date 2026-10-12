#!/usr/bin/env python3
"""Entry point of the packaged executables: the Windows one, the Linux AppImage.

PyInstaller needs a script to bundle, and `python -m greffier fenetre` is
not one. This file does nothing but what that command would do, with four
precautions an executable requires and the command line does not:

- **hand back on `--version`.** A graphical executable launched with no
  screen, a continuous integration runner for instance, cannot open a
  window. Its version can be checked without loading Tk or a model.
- **decode audio on `--check-audio`.** Exercise the shipped decoder without
  a model, microphone or window before publishing the executable.
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
import os
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
    if sys.argv[1:3] == ["-m", "greffier"]:
        # In a frozen application sys.executable is this launcher, not Python.
        # Its detached helpers must reach the CLI rather than open another GUI.
        from greffier.cli import application

        sys.argv = [sys.argv[0], *sys.argv[3:]]
        with contextlib.ExitStack() as files:
            for name in ("stdout", "stderr"):
                if getattr(sys, name) is None:
                    target = Path(os.environ.get("GREFFIER_COMPANION_LOG", os.devnull))
                    stream = files.enter_context(target.open("a", encoding="utf-8"))
                    setattr(sys, name, stream)
                    files.callback(setattr, sys, name, None)
            application()
        return 0
    if "--version" in sys.argv:
        print(f"Greffier {version()}")
        return 0
    if "--check-audio" in sys.argv:
        try:
            check_audio()
        except Exception:  # noqa: BLE001 - a failed check must never open a dialog
            with contextlib.suppress(OSError):
                log().write_text(traceback.format_exc(), encoding="utf-8")
            return 1
        return 0
    try:
        # Imported here and not at the top: on `--version`, loading the
        # interface would cost Tk and the models for a string.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window
        from greffier.locations import locate_tcl

        locate_tcl()
        Window(Config()).spin()
    except Exception:  # noqa: BLE001 - the last resort before a black screen
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


def check_audio() -> None:
    """Decode one synthetic second with the exact API used for transcription."""
    import math
    import struct
    import tempfile
    import wave

    import numpy as np
    from faster_whisper.audio import decode_audio

    rate = 16000
    samples = [int(16000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate)]
    with tempfile.TemporaryDirectory(prefix="greffier-audio-check-") as folder:
        audio = Path(folder) / "tone.wav"
        with wave.open(str(audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(struct.pack(f"<{rate}h", *samples))
        decoded = decode_audio(str(audio), sampling_rate=rate)
    if (decoded.shape != (rate,) or decoded.dtype != np.float32
            or not np.isfinite(decoded).all() or float(np.max(np.abs(decoded))) < 0.1):
        raise RuntimeError("The packaged audio decoder did not return the synthetic tone")


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
    except Exception:  # noqa: BLE001 - no Tk at all: the message goes to stderr
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
