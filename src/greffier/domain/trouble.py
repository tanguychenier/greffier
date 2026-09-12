"""What is worth writing down when something goes wrong.

A tool used by many people gets told « it did not work » and nothing else. What
is missing is never the report, it is what the machine saw at that moment: the
version, the system, and the sentence the failure carried. One line per
incident, in a file somebody can attach to a report without reading it.

Nothing personal goes in. Not the words of a meeting, not a name, not a path
inside somebody's account: an incident file has to be sendable without being
read, or it will not be sent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

_A_PATH = re.compile(r"(/[\w.\-]+){2,}|[A-Za-z]:\\[\w.\\\-]+")

_AN_ADDRESS = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b")

@dataclass(frozen=True, slots=True)
class Trouble:
    """One incident: where, what, and when."""

    where: str
    what: str
    when: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.where.strip():
            raise ValueError("un incident sans lieu ne se retrouve pas")

    def line(self, version: str = "", system: str = "") -> str:
        """The line as it is filed, already stripped of what is private."""
        morceaux = [self.when.isoformat(timespec="seconds"), self.where, without_traces(self.what)]
        if version:
            morceaux.insert(1, version)
        if system:
            morceaux.insert(1, system)
        return "\t".join(m.replace("\t", " ").replace("\n", " ") for m in morceaux if m)

def without_traces(what: str) -> str:
    """The sentence, minus the paths and the addresses it may carry.

    A failure often quotes the file it failed on, and that file sits in
    somebody's account, under their name, next to the subject of a meeting.
    """
    sans = _A_PATH.sub("<chemin>", what)
    return _AN_ADDRESS.sub("<adresse>", sans).strip()

def worth_keeping(lines: list[str], how_many: int = 200) -> list[str]:
    """The last incidents, the file never growing without end."""
    return lines[-how_many:] if how_many > 0 else []
