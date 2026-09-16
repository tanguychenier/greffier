"""What the tool knows, and how it hangs together.

The voice bank knows people and ignores subjects. The memory of meetings knows
decisions and ignores people. The documents know nobody. Each answers its own
question well and none answers the one somebody actually asks before a meeting:
« what do I already know about this? »

Nodes and edges, both pure. What a fact means, and what can be deduced from
several, is decided here; where facts are kept is not.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    PERSON = "personne"
    MEETING = "reunion"
    SUBJECT = "sujet"
    DOCUMENT = "document"
    DECISION = "decision"
    OPEN_POINT = "point-ouvert"
    SOURCE = "source"


class Link(StrEnum):
    ATTENDED = "a-participe"
    ABOUT = "porte-sur"
    DECIDED = "a-decide"
    LEFT_OPEN = "laisse-ouvert"
    SUPPLIED = "a-servi"
    OWNS = "porte"
    TRACKED_IN = "suivi-dans"


@dataclass(frozen=True, slots=True)
class Node:
    kind: Kind
    key: str
    label: str = ""
    said: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.label or self.key


@dataclass(frozen=True, slots=True)
class Edge:
    link: Link
    start: tuple[Kind, str]
    end: tuple[Kind, str]
    on: str = ""


@dataclass(frozen=True, slots=True)
class Known:
    """What is known around one subject, ready to open a meeting."""

    subject: str
    people: tuple[str, ...] = ()
    meetings: tuple[str, ...] = ()
    open_points: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.people or self.meetings or self.open_points
                    or self.documents or self.sources)

    def header(self) -> str:
        if self.empty:
            return ""
        lines = [f"[Ce qui est déjà connu sur « {self.subject} »]"]
        if self.meetings:
            lines.append("Réunions précédentes : " + ", ".join(self.meetings))
        if self.people:
            lines.append("Personnes qui y participent d'habitude : "
                          + ", ".join(self.people))
        if self.open_points:
            lines.append("Resté ouvert :")
            lines += [f"- {point}" for point in self.open_points]
        if self.documents:
            lines.append("Documents qui ont servi : " + ", ".join(self.documents))
        if self.sources:
            lines.append("Sources suivies : " + ", ".join(self.sources))
        return "\n".join(lines) + "\n\n"


def people_of(edges: Iterable[Edge], meetings: Iterable[str]) -> tuple[str, ...]:
    """Who attended these meetings, most recent first, each once."""
    wanted_ones = list(meetings)
    rang = {name: number for number, name in enumerate(wanted_ones)}
    found_ones: dict[str, int] = {}
    for edge in edges:
        if edge.link is not Link.ATTENDED:
            continue
        person, meeting = edge.start[1], edge.end[1]
        if meeting in rang:
            found_ones[person] = min(found_ones.get(person, len(wanted_ones)), rang[meeting])
    return tuple(sorted(found_ones, key=lambda name: found_ones[name]))


def from_trace(trace: object, subject: str = "") -> tuple[list[Node], list[Edge]]:
    """What one meeting adds to the index, from the trace it already leaves."""
    meeting = str(getattr(trace, "identifier", ""))
    if not meeting:
        return [], []
    when = str(getattr(trace, "held_on", ""))
    subject = subject.strip() or str(getattr(trace, "title", "")).strip()
    nodes = [Node(Kind.MEETING, meeting, str(getattr(trace, "title", "")))]
    edges: list[Edge] = []
    if subject:
        nodes.append(Node(Kind.SUBJECT, subject))
        edges.append(Edge(Link.ABOUT, (Kind.MEETING, meeting),
                          (Kind.SUBJECT, subject), when))
    for who in getattr(trace, "people", ()):
        nodes.append(Node(Kind.PERSON, who))
        edges.append(Edge(Link.ATTENDED, (Kind.PERSON, who),
                          (Kind.MEETING, meeting), when))
    for decision in getattr(trace, "decisions", ()):
        nodes.append(Node(Kind.DECISION, decision))
        edges.append(Edge(Link.DECIDED, (Kind.MEETING, meeting),
                          (Kind.DECISION, decision), when))
    for point in getattr(trace, "open_points", ()):
        nodes.append(Node(Kind.OPEN_POINT, point))
        edges.append(Edge(Link.LEFT_OPEN, (Kind.MEETING, meeting),
                          (Kind.OPEN_POINT, point), when))
    for document in getattr(trace, "documents", ()):
        nodes.append(Node(Kind.DOCUMENT, document))
        edges.append(Edge(Link.SUPPLIED, (Kind.DOCUMENT, document),
                          (Kind.MEETING, meeting), when))
    return nodes, edges
