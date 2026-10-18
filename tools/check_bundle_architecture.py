#!/usr/bin/env python3
"""Fail when a binary of a macOS bundle cannot run on the expected processor.

Running a bundle on its own runner proves nothing about the other processor:
that is how an arm64-only package was published as « the macOS bundle » up to
0.3.32, and an Intel Mac answered « bad CPU type in executable ». Every Mach-O
file of the bundle is asked which processors it carries.

The headers are read here rather than through `lipo`, so that the check is
tested on the Linux and Windows runners too, where there is no `lipo`.
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections.abc import Iterator
from pathlib import Path

CPU_TYPES = {
    0x01000007: "x86_64",
    0x0100000C: "arm64",
}

THIN_32 = b"\xce\xfa\xed\xfe"
THIN_64 = b"\xcf\xfa\xed\xfe"
FAT = b"\xca\xfe\xba\xbe"
FAT_64 = b"\xca\xfe\xba\xbf"

# A Java class file opens with the same four bytes as a fat binary; what
# follows is a version number in the forties or more, never a count of slices.
MOST_SLICES = 30

HEADER_SIZE = 8 + MOST_SLICES * 32


def architectures(header: bytes) -> frozenset[str] | None:
    """The processors a Mach-O file carries, or None when it is not one."""
    if len(header) < 8:
        return None
    magic = header[:4]
    if magic in (THIN_32, THIN_64):
        return frozenset({_name(struct.unpack_from("<I", header, 4)[0])})
    if magic in (FAT, FAT_64):
        return _fat(header, 32 if magic == FAT_64 else 20)
    return None


def _fat(header: bytes, slice_size: int) -> frozenset[str] | None:
    count = struct.unpack_from(">I", header, 4)[0]
    if not 0 < count <= MOST_SLICES or len(header) < 8 + count * slice_size:
        return None
    return frozenset(
        _name(struct.unpack_from(">I", header, 8 + index * slice_size)[0])
        for index in range(count)
    )


def _name(cpu_type: int) -> str:
    return CPU_TYPES.get(cpu_type, f"cpu-{cpu_type:#x}")


def strangers(bundle: Path, expected: str) -> Iterator[tuple[Path, frozenset[str]]]:
    """Every Mach-O file of the bundle that lacks the expected processor."""
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            carried = architectures(stream.read(HEADER_SIZE))
        if carried is not None and expected not in carried:
            yield path, carried


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--arch", required=True, choices=sorted(CPU_TYPES.values()))
    arguments = parser.parse_args(argv)
    if not arguments.bundle.is_dir():
        print(f"::error::{arguments.bundle}: no such bundle")
        return 1
    found = list(strangers(arguments.bundle, arguments.arch))
    for path, carried in found:
        print(f"::error::{path}: {', '.join(sorted(carried))}, not {arguments.arch}")
    if found:
        return 1
    print(f"Every binary of {arguments.bundle.name} runs on {arguments.arch}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
