"""What the window computes before showing, testable without a screen."""

from __future__ import annotations

import contextlib
from pathlib import Path


def clock(seconds: float) -> str:
    """The meeting's stopwatch."""
    entier = max(0, int(seconds))
    heures, remaining = divmod(entier, 3600)
    minutes, restantes = divmod(remaining, 60)
    if heures:
        return f"{heures}:{minutes:02d}:{restantes:02d}"
    return f"{minutes}:{restantes:02d}"

def readable_subject(identifier: str, minutes: Path, subject: str = "") -> str:
    """The meeting's subject: the chosen one, else what was written."""
    if subject.strip():
        return subject.strip()
    if minutes.exists():
        with contextlib.suppress(OSError):
            from greffier.domain.minutes import title as extraire_titre

            title = extraire_titre(minutes.read_text(encoding="utf-8"), "")
            if title:
                without_prefix = title.split(":", 1)[-1].strip() if ":" in title else title
                return without_prefix or title
    return identifier

ETIREMENT_MAXIMUM = 1.25

def button_grid(
    largeurs: list[int], offerte: int, gap: int = 9
) -> tuple[int, int]:
    """The grid of a button bar: (buttons per row, column width).

    Here and not in the drawn widget: what touches Tk is not covered by the
    tests, for want of a display server in continuous integration, and this
    computation is where the defect lived. The seventh button of the Meetings
    tab fell outside the window, invisible and unreachable.

    Three rules, and they go together:

    **Columns of equal width.** Buttons of different widths do not fall together
    from one row to the next, and a bar whose edges do not line up reads as
    sloppy. There is therefore one column width, and the widest label sets its
    minimum.

    **The rows are balanced.** It looks for the smallest number of rows, then
    spreads them evenly: seven buttons over two rows give 4 and 3, never 5 and 2.
    A full first row against an almost empty second one is the most visible
    defect of a bar that wraps.

    **The stretching is capped.** The columns take the room available, but no
    more than a quarter beyond what the label asks for: in a 1 280 px window,
    filling without a limit gave 290 px buttons for an « Ouvrir » that needs 96,
    stretched over nothing. A button out of proportion is as badly laid out as
    one that overflows.
    """
    total = len(largeurs)
    if not total:
        return (1, 0)
    demandee = max(largeurs)
    plafond = int(demandee * ETIREMENT_MAXIMUM)
    for rangs in range(1, total + 1):
        by_rank = -(-total // rangs)  # division entière par excès
        if by_rank * demandee + (by_rank - 1) * gap <= offerte:
            break
    else:
        by_rank = 1
    available = (offerte - (by_rank - 1) * gap) // by_rank
    colonne = max(demandee, min(plafond, available))
    return (by_rank, colonne)

def dot_marker(count: int) -> str:
    """What a tab badge shows for this count. Empty for nothing.

    Here rather than in the drawn shape: what touches Tk is not covered by the
    tests, for want of a display server in continuous integration, and it is the
    number that carries the rule.

    Past nine the exact number helps nobody: what matters is that there are many,
    and two digits would overflow the disc.
    """
    if count <= 0:
        return ""
    return str(count) if count < 10 else "9+"

def live_state_line(in_a_meeting: bool, annonce: str, sentences: int) -> str:
    """The line that says what the thread is doing, or why it is doing nothing.

    An empty tab reads as "nobody is speaking" when it often means "nothing is
    listening": a missing model, a process never started, a meeting already over.
    The difference is between waiting and losing your meeting.
    """
    if not in_a_meeting:
        return (
            "Aucune réunion en cours. Pendant une réunion, ce qui se dit "
            "s'affiche ici et le locuteur se corrige d'un clic sur son nom."
        )
    if sentences == 0:
        awaiting = annonce or "En attente de la première tranche…"
        return f"{awaiting} Cliquez sur un nom pour corriger qui parle."
    aide = (
        "Cliquez sur un nom pour corriger qui parle : « ? » signale un nom reconnu "
        "par la voix, pas encore confirmé."
    )
    return f"{sentences} phrase(s) transcrite(s). {aide}"
