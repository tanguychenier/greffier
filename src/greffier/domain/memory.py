"""What a meeting leaves for the ones that follow.

The voice bank already carries people from one meeting to the next. What was
decided, what was left hanging and which documents were handed over did not: a
second meeting on the same work started from nothing, and the room had to say
again what it had said a week before.

Pure: reading the minutes is text in, structure out, and choosing what fits in
the room available is arithmetic. Where any of it is kept is somebody else's
business.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Room given to the recalled section of the header. Measured against the rest:
#: the glossary takes 850 at most, the documents 24 000, and what is left of a
#: model's attention after that is not worth spending on older meetings.
MAXIMUM_REMINDER = 2_000

_TITLES = {
    "decisions": ("décisions", "decisions"),
    "open_points": ("points ouverts", "points en suspens", "open points"),
}


@dataclass(frozen=True, slots=True)
class Trace:
    """What one meeting leaves behind, in the words of its own minutes."""

    identifier: str
    title: str
    held_on: str = ""
    people: tuple[str, ...] = field(default=())
    decisions: tuple[str, ...] = field(default=())
    open_points: tuple[str, ...] = field(default=())
    documents: tuple[str, ...] = field(default=())

    @property
    def empty(self) -> bool:
        """A meeting that decided nothing and left nothing is not worth recalling."""
        return not (self.decisions or self.open_points or self.documents)

    def rendered(self) -> str:
        """The trace as the writer reads it, one meeting in a few lines."""
        when = f" ({self.held_on})" if self.held_on else ""
        lines = [f"- {short_title(self.title) or self.identifier}{when}"]
        if self.people:
            lines.append(f"  Présents : {', '.join(self.people)}")
        for heading, points in (("Décidé", self.decisions),
                                 ("Resté ouvert", self.open_points)):
            for point in points:
                lines.append(f"  {heading} : {point}")
        if self.documents:
            lines.append(f"  Documents fournis : {', '.join(self.documents)}")
        return "\n".join(lines)


#: What the minutes put in front of their own title. Recalled as they come, the
#: older meetings all start with the same three words, which says nothing and
#: costs room.
_HEADER = re.compile(r"^\s*compte[- ]rendu(\s+de\s+r[ée]union)?\s*[:—-]\s*", re.I)


def short_title(title: str) -> str:
    """The title of a meeting, without the words every set of minutes carries."""
    return _HEADER.sub("", title).strip() or title.strip()


def what_the_minutes_left(minutes: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The decisions and the open points, read from the minutes themselves.

    Read rather than asked for a second time: the model has already sorted that
    material once, and asking again would cost a call, and give a different
    answer to the same question.
    """
    return _bullets_under(minutes, "decisions"), _bullets_under(minutes, "open_points")


def _bullets_under(minutes: str, which: str) -> tuple[str, ...]:
    sections = re.split(r"^##\s+", minutes, flags=re.M)[1:]
    for section in sections:
        title, _, corps = section.partition("\n")
        if title.strip().lower().rstrip(" :") not in _TITLES[which]:
            continue
        points = [
            re.sub(r"\s+", " ", line.lstrip("-*").strip())
            for line in corps.splitlines()
            if line.lstrip().startswith(("-", "*"))
        ]
        return tuple(p for p in points if p)
    return ()


def recalled(traces: list[Trace], place: int = MAXIMUM_REMINDER) -> str:
    """The section handed to the writer: the most recent first, within the room.

    Cut by meeting and never mid-meeting: half a decision recalled is worse than
    a decision not recalled, because nothing says it was cut.
    """
    retained_ones: list[str] = []
    length = 0
    for trace in traces:
        if trace.empty:
            continue
        rendered = trace.rendered()
        if length + len(rendered) + 1 > place:
            break
        retained_ones.append(rendered)
        length += len(rendered) + 1
    if not retained_ones:
        return ""
    return (
        "[Ce que les réunions précédentes ont laissé]\n"
        "De la plus récente à la plus ancienne. N'y fais référence que si la "
        "réunion en cours y touche, et ne présente jamais un point ancien comme "
        "s'il venait d'être dit :\n"
        + "\n".join(retained_ones)
        + "\n\n"
    )
