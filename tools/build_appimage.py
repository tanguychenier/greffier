#!/usr/bin/env python3
"""Builds the Linux AppImage: one file to download, mark executable, double-click.

    python3 tools/build_appimage.py            # dist/Greffier-x86_64.AppImage
    python3 tools/build_appimage.py --check    # then runs it with --version

Three steps, each of which can be run and looked at on its own. PyInstaller
folds the interpreter, the package, its sentences and the native libraries
of sherpa-onnx into `dist/Greffier/`, the same command as the Windows
executable. An AppDir is laid out around it: `AppRun`, a desktop entry, the
icon pulled out of the macOS one (an icns is a bag of PNGs, no library
needed). `appimagetool` then wraps the AppDir; it is fetched once from its
own releases and kept next to the build.

The models are not in it, on purpose: they live outside the application, so
that an update keeps them, and the window fetches them on first launch.
ffmpeg is not in it either, it is a system package, and the launcher says so
plainly when it is missing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APPDIR = DIST / "Greffier.AppDir"
NAME = "Greffier"
APPIMAGETOOL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)

DESKTOP = """[Desktop Entry]
Type=Application
Name=Greffier
Comment=Enregistre la réunion et en rédige le compte rendu
Exec=Greffier
Icon=greffier
Categories=Office;AudioVideo;
Terminal=false
"""

APPRUN = """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Greffier/Greffier" "$@"
"""


def say(text: str) -> None:
    print(f"  {text}", flush=True)


def icon_from_icns(icns: Path, wanted: bytes = b"ic08") -> bytes:
    """The 256-pixel PNG kept inside the macOS icon.

    An icns file is a sequence of blocks, four bytes of type, four of
    length, then the data; the big ones are plain PNGs. `ic08` is 256 x 256.
    """
    data = icns.read_bytes()
    if data[:4] != b"icns":
        raise ValueError(f"{icns} is not an icns file")
    position = 8
    fallback = b""
    while position + 8 <= len(data):
        kind = data[position:position + 4]
        length = struct.unpack(">I", data[position + 4:position + 8])[0]
        block = data[position + 8:position + length]
        if block[:8] == b"\x89PNG\r\n\x1a\n":
            if kind == wanted:
                return block
            fallback = fallback or block
        position += max(length, 8)
    if not fallback:
        raise ValueError(f"no PNG inside {icns}")
    return fallback


def bundle(python: Path) -> Path:
    """PyInstaller, the same command as the Windows executable."""
    say("PyInstaller…")
    subprocess.run(
        [str(python), "-m", "PyInstaller", "--noconfirm", "--name", NAME, "--windowed",
         "--collect-all", "sherpa_onnx", "--collect-all", "soundfile",
         "--collect-submodules", "greffier", "--collect-data", "greffier",
         "--distpath", str(DIST), "--workpath", str(DIST / "build"),
         "--specpath", str(DIST / "build"),
         str(ROOT / "tools" / "launcher.py")],
        check=True, cwd=ROOT,
    )
    built = DIST / NAME / NAME
    if not built.exists():
        raise FileNotFoundError(built)
    return DIST / NAME


def lay_out(bundled: Path) -> Path:
    """The AppDir around the bundle: AppRun, the desktop entry, the icon."""
    say("AppDir…")
    if APPDIR.exists():
        shutil.rmtree(APPDIR)
    target = APPDIR / "usr" / "bin" / NAME
    target.parent.mkdir(parents=True)
    shutil.copytree(bundled, target)
    run = APPDIR / "AppRun"
    run.write_text(APPRUN, encoding="utf-8")
    run.chmod(run.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (APPDIR / "greffier.desktop").write_text(DESKTOP, encoding="utf-8")
    icon = icon_from_icns(ROOT / "macos" / "Greffier.icns")
    (APPDIR / "greffier.png").write_bytes(icon)
    (APPDIR / ".DirIcon").write_bytes(icon)
    return APPDIR


def the_tool() -> Path:
    """appimagetool, fetched once and kept next to the build."""
    tool = DIST / "appimagetool-x86_64.AppImage"
    if not tool.exists():
        say("fetching appimagetool…")
        DIST.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(APPIMAGETOOL, timeout=120) as response:
            tool.write_bytes(response.read())
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


def wrap(appdir: Path) -> Path:
    """The AppImage itself. Without FUSE, the tool runs extracted."""
    say("appimagetool…")
    target = DIST / f"{NAME}-x86_64.AppImage"
    environment = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    subprocess.run([str(the_tool()), str(appdir), str(target)], check=True,
                   env=environment, cwd=DIST)
    return target


def check(appimage: Path) -> str:
    """Runs the AppImage on --version, the only check a screenless machine allows."""
    say("--version…")
    done = subprocess.run(
        [str(appimage), "--version"], capture_output=True, text=True, check=True,
        env=dict(os.environ, APPIMAGE_EXTRACT_AND_RUN="1"), timeout=120,
    )
    return done.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="run the result on --version")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    options = parser.parse_args()
    appimage = wrap(lay_out(bundle(options.python)))
    size = appimage.stat().st_size / 1024**2
    print(f"✓ {appimage} ({size:.0f} Mo)")
    if options.check:
        print(f"✓ {check(appimage)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
