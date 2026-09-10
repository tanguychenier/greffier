"""Comparing two versions, to know whether there is better elsewhere."""

from __future__ import annotations

import re

_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")


def read(brute: str) -> tuple[int, int, int] | None:
    """The three numbers of a version, or None when it is not one."""
    trouve = _VERSION.match(brute.strip())
    if trouve is None:
        return None
    majeure, mineure, corrective = trouve.groups()
    return (int(majeure), int(mineure), int(corrective or 0))


def is_newer(candidate: str, installed: str) -> bool:
    """True when `candidate` is strictly later than `installed`."""
    une, autre = read(candidate), read(installed)
    if une is None or autre is None:
        return False
    return une > autre
