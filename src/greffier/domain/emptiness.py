"""What a list says when it holds nothing, and whether its buttons may act.

An empty table under four live buttons tells nobody what is missing, nor what
to do about it. Reported in use on the « Voix » tab: four actions stayed
pressable with nothing to press them on, and the table said only that it was
empty, which the eye had already seen.

Empty is not a failure here. A first meeting, a meeting not yet chosen, a
recording not yet started: each is an ordinary moment of the work, and each
calls for a different sentence.
"""

from __future__ import annotations

from enum import Enum, auto


class Missing(Enum):
    """Why a list holds nothing. None of these is an error."""

    NO_MEETING_YET = auto()
    NO_MEETING_CHOSEN = auto()
    NO_VOICE_TO_NAME = auto()
    NO_THREAD_YET = auto()

def meetings(how_many: int) -> Missing | None:
    """The list of meetings: empty only before the first one."""
    return Missing.NO_MEETING_YET if how_many == 0 else None

def voices(a_meeting_is_chosen: bool, how_many: int) -> Missing | None:
    """The voices of a meeting: two reasons to be empty, and they differ.

    Nothing chosen is not the same as nothing to name: the first asks for a
    click, the second says the work is done.
    """
    if not a_meeting_is_chosen:
        return Missing.NO_MEETING_CHOSEN
    return Missing.NO_VOICE_TO_NAME if how_many == 0 else None

def thread(how_many: int) -> Missing | None:
    """The live thread: empty until somebody speaks."""
    return Missing.NO_THREAD_YET if how_many == 0 else None

def may_act(missing: Missing | None) -> bool:
    """Whether the buttons beside the list have anything to act on."""
    return missing is None
