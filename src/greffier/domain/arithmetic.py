"""How many threads to give the models, and why not all of them."""

from __future__ import annotations

import os


def compute_threads(coeurs: int | None = None) -> int:
    """Half the cores, at least one."""
    disponibles = coeurs if coeurs is not None else (os.cpu_count() or 2)
    return max(1, disponibles // 2)
