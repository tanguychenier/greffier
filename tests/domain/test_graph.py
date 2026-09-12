"""What the tool knows, and how it hangs together."""

from __future__ import annotations

from dataclasses import dataclass, field

from greffier.domain.graph import Edge, Kind, Known, Link, from_trace, people_of


@dataclass
class FauxTrace:
    identifier: str = "2026-09-12_recette"
    title: str = "point sur la recette"
    held_on: str = "2026-09-12"
    people: tuple[str, ...] = ("Jacques", "Sophie")
    decisions: tuple[str, ...] = ("Recette décalée à jeudi.",)
    open_points: tuple[str, ...] = ("Validation fonctionnelle.",)
    documents: tuple[str, ...] = field(default=())


class TestWhatAMeetingAddsToTheIndex:
    def test_the_meeting_and_its_subject(self):
        nodes, edges = from_trace(FauxTrace(), "recette")
        assert any(n.kind is Kind.SUBJECT and n.key == "recette" for n in nodes)
        assert any(e.link is Link.ABOUT for e in edges)

    def test_the_people_who_were_there(self):
        _, edges = from_trace(FauxTrace(), "recette")
        venus = {e.start[1] for e in edges if e.link is Link.ATTENDED}
        assert venus == {"Jacques", "Sophie"}

    def test_what_was_decided_and_what_stayed_open(self):
        _, edges = from_trace(FauxTrace(), "recette")
        assert any(e.link is Link.DECIDED for e in edges)
        assert any(e.link is Link.LEFT_OPEN for e in edges)

    def test_without_a_subject_the_title_serves(self):
        """Nothing is deduced: the title is what somebody wrote, at least."""
        nodes, _ = from_trace(FauxTrace(), "")
        assert any(n.kind is Kind.SUBJECT and n.key == "point sur la recette"
                   for n in nodes)

    def test_a_trace_without_a_meeting_adds_nothing(self):
        assert from_trace(FauxTrace(identifier="")) == ([], [])


class TestWhoUsuallyAttends:
    def test_most_recent_first(self):
        edges = [
            Edge(Link.ATTENDED, (Kind.PERSON, "Sophie"), (Kind.MEETING, "vieille")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "recente")),
        ]
        assert people_of(edges, ["recente", "vieille"]) == ("Jacques", "Sophie")

    def test_somebody_at_several_meetings_is_named_once(self):
        edges = [
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "recente")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "vieille")),
        ]
        assert people_of(edges, ["recente", "vieille"]) == ("Jacques",)

    def test_other_meetings_are_ignored(self):
        edges = [Edge(Link.ATTENDED, (Kind.PERSON, "Ailleurs"),
                      (Kind.MEETING, "autre-sujet"))]
        assert people_of(edges, ["recente"]) == ()


class TestWhatAPreparationOpensOn:
    def test_it_says_what_is_known_and_nothing_when_nothing_is(self):
        assert Known("recette").header() == ""
        entete = Known("recette", people=("Jacques",), meetings=("r1",)).header()
        assert "Jacques" in entete and "recette" in entete
