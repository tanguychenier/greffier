"""The boxes that ask, and what they do when nobody is there to answer.

A modal box is a question put to a person. Opened where there is no person --
a test run, the proof of the window, a virtual screen -- it waits for an answer
that never comes, and the application hangs with nothing on screen saying why.

That is not a hypothesis. `Window.__init__` offered to fetch the missing models
before the window had been painted once, so on a machine with no models
`tools/window_proof.py` stopped there and stayed: the proof of the window could
not run on the only kind of machine it is meant to photograph, and the suite's
own window fixture was written and then used by no test at all.

Every box therefore goes through here, and here knows whether anybody is
watching. With nobody there, nothing opens, the answer is the one that changes
the least -- no -- and the question is kept so that a test can read what would
have been shown.
"""

from __future__ import annotations

import os
from tkinter import messagebox
from typing import Literal

TEST_SCREEN = "GREFFIER_ECRAN_D_ESSAI"
"""Set by the suite and by the window proof, on a screen they created."""

_unanswered: list[str] = []


def somebody_is_there() -> bool:
    """Whether a person can answer a box right now."""
    return not os.environ.get(TEST_SCREEN)


def unanswered() -> list[str]:
    """What would have been shown, on a screen with nobody in front of it."""
    return list(_unanswered)


def forget_what_was_asked() -> None:
    """Empties that record, so one test cannot read another's questions."""
    _unanswered.clear()


def ask_yes_no(
    title: str, question: str, *, default: Literal["yes", "no"] = "yes"
) -> bool:
    """Asks, and answers no where there is nobody to ask.

    No, and never yes: every question here guards something that costs -- a
    gigabyte fetched, a mail sent, a recording erased. Doing none of it is the
    answer one can take back.
    """
    if not somebody_is_there():
        _unanswered.append(question)
        return False
    return bool(messagebox.askyesno(title, question, default=default))


def tell(title: str, message: str) -> None:
    """Says something that needs acknowledging."""
    if not somebody_is_there():
        _unanswered.append(message)
        return
    messagebox.showinfo(title, message)


def warn(title: str, message: str) -> None:
    """Says something that is not yet a failure."""
    if not somebody_is_there():
        _unanswered.append(message)
        return
    messagebox.showwarning(title, message)


def complain(title: str, message: str) -> None:
    """Says what went wrong."""
    if not somebody_is_there():
        _unanswered.append(message)
        return
    messagebox.showerror(title, message)
