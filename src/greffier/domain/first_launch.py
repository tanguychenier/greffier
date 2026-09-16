"""What a fresh machine still has to do before its first meeting.

Three things, and nothing else: the models, the account that writes, a
microphone. Said in the order they are needed, with what is already done
ticked, so that somebody who has just double-clicked the tool is taken by
the hand rather than left in front of six tabs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Step:
    """One thing to do, and whether it is done."""

    key: str
    done: bool


def steps(models_present: bool, claude_signed_in: bool, microphone_chosen: bool) -> list[Step]:
    return [
        Step("modeles", models_present),
        Step("compte", claude_signed_in),
        Step("micro", microphone_chosen),
    ]


def is_a_first_launch(the_steps: list[Step]) -> bool:
    """Whether the hand is still needed: as long as something is not done."""
    return any(not step.done for step in the_steps)


def next_to_do(the_steps: list[Step]) -> Step | None:
    """The first thing not done, in the order things are needed."""
    return next((step for step in the_steps if not step.done), None)
