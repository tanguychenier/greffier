#!/usr/bin/env python3
"""Fail when an executable script of a bundle names an interpreter a Mac lacks.

A script is run through the interpreter on its first line. The bundle is
built in a temporary workshop and moved afterwards, so a script that names
an interpreter by absolute path names the workshop: up to 0.3.33 every
launcher in Greffier.app/Contents/bin began with
`#!/var/folders/…/greffier-paquet.XXXXXX/Greffier.app/Contents/MacOS/Greffier`
and answered « bad interpreter » on every Mac. Only the system's own folders
are on every Mac, so only they may be named.

Only executable files are read: a library module whose first line is a
shebang is imported, never run, and its first line says nothing.
"""

from __future__ import annotations

import argparse
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

# The folders every Mac carries, whatever was installed on it.
SYSTEM_FOLDERS = ("/bin/", "/usr/bin/")

# Longer than any interpreter path, short enough to read every file quickly.
FIRST_LINE = 512


def interpreter(head: bytes) -> str | None:
    """The interpreter a script's first line names, or None for no shebang."""
    if not head.startswith(b"#!"):
        return None
    line = head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    return line.split()[0] if line else ""


def portable(named: str) -> bool:
    return named.startswith(SYSTEM_FOLDERS)


def dangling(bundle: Path) -> Iterator[tuple[Path, str]]:
    """Every executable script of the bundle whose interpreter is not portable."""
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if not path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            continue
        with path.open("rb") as stream:
            named = interpreter(stream.read(FIRST_LINE))
        if named is not None and not portable(named):
            yield path, named


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    arguments = parser.parse_args(argv)
    if not arguments.bundle.is_dir():
        print(f"::error::{arguments.bundle}: no such bundle")
        return 1
    found = list(dangling(arguments.bundle))
    for path, named in found:
        print(f"::error::{path}: runs through {named or 'nothing'}, "
              f"which is not on every Mac")
    if found:
        return 1
    print(f"Every script of {arguments.bundle.name} runs through an interpreter"
          " every Mac has.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
