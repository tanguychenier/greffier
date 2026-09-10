"""Comparing two versions, to know whether there is better elsewhere."""

from __future__ import annotations

import re

_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")


def read(brute: str) -> tuple[int, int, int] | None:
    """The three numbers of a version, or None when it is not one."""
    found = _VERSION.match(brute.strip())
    if found is None:
        return None
    majeure, mineure, corrective = found.groups()
    return (int(majeure), int(mineure), int(corrective or 0))


def is_newer(candidate: str, installed: str) -> bool:
    """True when `candidate` is strictly later than `installed`."""
    one_of, other = read(candidate), read(installed)
    if one_of is None or other is None:
        return False
    return one_of > other
