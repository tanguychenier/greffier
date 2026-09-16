"""What the machine can give the models, and why not all of it."""

from __future__ import annotations

import os

AUTO = "auto"

CARD = "cuda"

PROCESSOR = "cpu"

def compute_threads(cores: int | None = None) -> int:
    """Half the cores, at least one."""
    available_ones = cores if cores is not None else (os.cpu_count() or 2)
    return max(1, available_ones // 2)

def chosen_device(wish: str, a_card_answers: bool) -> str:
    """The device to hand the models: what was asked, or what is there.

    A wish for the card on a machine without one is not a mistake to report: the
    same settings travel from one machine to another, and a meeting transcribed
    slowly beats a meeting refused.
    """
    if wish == CARD and not a_card_answers:
        return PROCESSOR
    if wish in (CARD, PROCESSOR):
        return wish
    return CARD if a_card_answers else PROCESSOR
