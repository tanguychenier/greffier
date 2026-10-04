"""What the tool knows, and how it hangs together."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from greffier.domain.graph import Edge, Kind, Known, Link, Node, from_trace, people_of

# mutmut forks every mutant run from the process that has already run the suite
# twice, once to see which test reaches which function and once clean. A @given
# method is then called on a new instance of its class each time, which
# Hypothesis reports as « differing executors » and fails whatever the code
# does. Measured on 2026-10-04: a fresh « mutmut run » stopped at its clean step
# on the first property test below. The profile's other settings are kept.
mutmut_safe = settings(suppress_health_check=[*settings.default.suppress_health_check,
                                              HealthCheck.differing_executors])


@dataclass
class FauxTrace:
    identifier: str = "2026-09-12_recette"
    title: str = "point sur la recette"
    held_on: str = "2026-09-12"
    people: tuple[str, ...] = ("Jacques", "Sophie")
    decisions: tuple[str, ...] = ("Recette décalée à jeudi.",)
    open_points: tuple[str, ...] = ("Validation fonctionnelle.",)
    documents: tuple[str, ...] = field(default=())


# What somebody types as a name, a title or a point: no newline, since a header
# line has to stay one line, and no comma, since « , » is the separator the
# header puts between names and the tests read it back.
WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZéèçà0123456789-",
               min_size=1, max_size=12)
# Unique, so that « each once » can be read off a count.
WORDS = st.lists(WORD, max_size=4, unique=True).map(tuple)

TRACES = st.builds(FauxTrace, identifier=WORD, title=WORD, held_on=WORD,
                   people=WORDS, decisions=WORDS, open_points=WORDS, documents=WORDS)
KNOWN = st.builds(Known, subject=WORD, people=WORDS, meetings=WORDS,
                  open_points=WORDS, documents=WORDS, sources=WORDS)

# A small cast and a few meetings, so that the same person attends several
# meetings and two people are often ranked against each other. Amina and Zoé
# sit at the two ends of the alphabet: the alphabet and the dates disagree.
PEOPLE = ("Jacques", "Sophie", "Amina", "Zoé")
MEETINGS = ("2026-09-12_recette", "2026-09-05_recette", "2026-08-29_recette",
            "2026-08-22_recette")
ATTENDANCES = st.builds(
    Edge, link=st.just(Link.ATTENDED),
    start=st.tuples(st.just(Kind.PERSON), st.sampled_from(PEOPLE)),
    end=st.tuples(st.just(Kind.MEETING), st.sampled_from((*MEETINGS, "2026-09-01_autre"))),
)
OTHER_LINKS = st.one_of(
    st.builds(Edge, link=st.just(Link.ABOUT),
              start=st.tuples(st.just(Kind.MEETING), st.sampled_from(MEETINGS)),
              end=st.just((Kind.SUBJECT, "recette"))),
    st.builds(Edge, link=st.just(Link.SUPPLIED),
              start=st.just((Kind.DOCUMENT, "cahier-des-charges.pdf")),
              end=st.tuples(st.just(Kind.MEETING), st.sampled_from(MEETINGS))),
)
EDGES = st.lists(st.one_of(ATTENDANCES, OTHER_LINKS), max_size=10)
WANTED_MEETINGS = st.lists(st.sampled_from(MEETINGS), min_size=1, max_size=4, unique=True)


class TestWhatAMeetingAddsToTheIndex:
    def test_the_meeting_and_its_subject(self):
        nodes, edges = from_trace(FauxTrace(), "recette")
        assert any(n.kind is Kind.SUBJECT and n.key == "recette" for n in nodes)
        assert any(e.link is Link.ABOUT for e in edges)

    def test_the_meeting_itself_keeps_its_title(self):
        nodes, _ = from_trace(FauxTrace(), "recette")
        assert Node(Kind.MEETING, "2026-09-12_recette", "point sur la recette") in nodes

    def test_the_meeting_bears_on_its_subject_from_the_day_it_was_held(self):
        _, edges = from_trace(FauxTrace(), "recette")
        assert Edge(Link.ABOUT, (Kind.MEETING, "2026-09-12_recette"),
                    (Kind.SUBJECT, "recette"), "2026-09-12") in edges

    def test_every_link_is_dated_the_day_the_meeting_was_held(self):
        _, edges = from_trace(FauxTrace(), "recette")
        assert edges and all(e.on == "2026-09-12" for e in edges)

    def test_the_people_who_were_there(self):
        _, edges = from_trace(FauxTrace(), "recette")
        venus = {e.start[1] for e in edges if e.link is Link.ATTENDED}
        assert venus == {"Jacques", "Sophie"}

    def test_a_person_is_a_node_linked_to_the_meeting_they_attended(self):
        nodes, edges = from_trace(FauxTrace(people=("Jacques",)), "recette")
        assert Node(Kind.PERSON, "Jacques") in nodes
        assert Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"),
                    (Kind.MEETING, "2026-09-12_recette"), "2026-09-12") in edges

    def test_what_was_decided_and_what_stayed_open(self):
        _, edges = from_trace(FauxTrace(), "recette")
        assert any(e.link is Link.DECIDED for e in edges)
        assert any(e.link is Link.LEFT_OPEN for e in edges)

    def test_the_documents_that_served_point_at_the_meeting(self):
        trace = FauxTrace(documents=("cahier-des-charges.pdf",))
        nodes, edges = from_trace(trace, "recette")
        assert Node(Kind.DOCUMENT, "cahier-des-charges.pdf") in nodes
        assert Edge(Link.SUPPLIED, (Kind.DOCUMENT, "cahier-des-charges.pdf"),
                    (Kind.MEETING, "2026-09-12_recette"), "2026-09-12") in edges

    def test_without_a_subject_the_title_serves(self):
        """Nothing is deduced: the title is what somebody wrote, at least."""
        nodes, _ = from_trace(FauxTrace(), "")
        assert any(n.kind is Kind.SUBJECT and n.key == "point sur la recette"
                   for n in nodes)

    def test_a_subject_made_of_blanks_is_no_subject(self):
        nodes, _ = from_trace(FauxTrace(), "   ")
        assert Node(Kind.SUBJECT, "point sur la recette") in nodes
        assert Node(Kind.SUBJECT, "   ") not in nodes

    def test_the_subject_is_kept_without_its_surrounding_blanks(self):
        nodes, edges = from_trace(FauxTrace(), "  recette ")
        assert Node(Kind.SUBJECT, "recette") in nodes
        assert any(e.link is Link.ABOUT and e.end == (Kind.SUBJECT, "recette") for e in edges)

    def test_with_neither_subject_nor_title_the_meeting_is_about_nothing(self):
        nodes, edges = from_trace(FauxTrace(title=""))
        assert not any(n.kind is Kind.SUBJECT for n in nodes)
        assert not any(e.link is Link.ABOUT for e in edges)

    def test_a_trace_without_a_meeting_adds_nothing(self):
        assert from_trace(FauxTrace(identifier="")) == ([], [])

    def test_an_object_that_is_not_even_a_trace_adds_nothing(self):
        assert from_trace(object()) == ([], [])

    def test_a_trace_that_knows_only_its_identifier_adds_the_meeting_alone(self):
        """The index reads a trace attribute by attribute and takes what is there:
        a meeting with no title, no date and nothing attached is still a meeting."""
        nodes, edges = from_trace(SimpleNamespace(identifier="2026-09-12_recette"))
        assert nodes == [Node(Kind.MEETING, "2026-09-12_recette")]
        assert edges == []

    def test_a_trace_that_does_not_say_when_leaves_its_links_undated(self):
        trace = SimpleNamespace(identifier="2026-09-12_recette", people=("Jacques",))
        _, edges = from_trace(trace)
        assert edges == [Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"),
                              (Kind.MEETING, "2026-09-12_recette"), "")]

    @mutmut_safe
    @given(trace=TRACES, subject=WORD)
    def test_everything_the_trace_says_is_indexed_once_and_dated(self, trace, subject):
        nodes, edges = from_trace(trace, subject)
        meeting = (Kind.MEETING, trace.identifier)
        when = trace.held_on
        assert nodes[0] == Node(Kind.MEETING, trace.identifier, trace.title)
        assert Node(Kind.SUBJECT, subject) in nodes
        assert Edge(Link.ABOUT, meeting, (Kind.SUBJECT, subject), when) in edges
        for who in trace.people:
            assert Node(Kind.PERSON, who) in nodes
            assert Edge(Link.ATTENDED, (Kind.PERSON, who), meeting, when) in edges
        for decision in trace.decisions:
            assert Node(Kind.DECISION, decision) in nodes
            assert Edge(Link.DECIDED, meeting, (Kind.DECISION, decision), when) in edges
        for point in trace.open_points:
            assert Node(Kind.OPEN_POINT, point) in nodes
            assert Edge(Link.LEFT_OPEN, meeting, (Kind.OPEN_POINT, point), when) in edges
        for document in trace.documents:
            assert Node(Kind.DOCUMENT, document) in nodes
            assert Edge(Link.SUPPLIED, (Kind.DOCUMENT, document), meeting, when) in edges
        said = (len(trace.people) + len(trace.decisions) + len(trace.open_points)
                + len(trace.documents))
        assert len(nodes) == 2 + said
        assert len(edges) == 1 + said

    @mutmut_safe
    @given(trace=TRACES)
    def test_the_people_it_records_are_the_people_read_back(self, trace):
        """The index is written by from_trace and read by people_of: they agree."""
        _, edges = from_trace(trace, "recette")
        assert people_of(edges, [trace.identifier]) == trace.people


class TestWhoUsuallyAttends:
    def test_most_recent_first(self):
        edges = [
            Edge(Link.ATTENDED, (Kind.PERSON, "Sophie"), (Kind.MEETING, "vieille")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "recente")),
        ]
        assert people_of(edges, ["recente", "vieille"]) == ("Jacques", "Sophie")

    def test_recency_beats_the_alphabet(self):
        edges = [
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "vieille")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Sophie"), (Kind.MEETING, "recente")),
        ]
        assert people_of(edges, ["recente", "vieille"]) == ("Sophie", "Jacques")

    def test_somebody_at_several_meetings_is_named_once(self):
        edges = [
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "recente")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "vieille")),
        ]
        assert people_of(edges, ["recente", "vieille"]) == ("Jacques",)

    def test_somebody_is_placed_by_their_most_recent_meeting_even_when_read_first(self):
        edges = [
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "recente")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Sophie"), (Kind.MEETING, "entre")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "vieille")),
        ]
        assert people_of(edges, ["recente", "entre", "vieille"]) == ("Jacques", "Sophie")

    def test_other_meetings_are_ignored(self):
        edges = [Edge(Link.ATTENDED, (Kind.PERSON, "Ailleurs"),
                      (Kind.MEETING, "autre-sujet"))]
        assert people_of(edges, ["recente"]) == ()

    def test_a_link_of_another_kind_is_skipped_and_the_reading_goes_on(self):
        edges = [
            Edge(Link.ABOUT, (Kind.MEETING, "recente"), (Kind.SUBJECT, "recette")),
            Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "recente")),
        ]
        assert people_of(edges, ["recente"]) == ("Jacques",)

    @mutmut_safe
    @given(edges=EDGES, meetings=WANTED_MEETINGS)
    def test_each_attendee_once_most_recent_first_whatever_the_order_of_the_edges(
            self, edges, meetings):
        rank = {meeting: number for number, meeting in enumerate(meetings)}
        attendances = [(e.start[1], e.end[1]) for e in edges
                       if e.link is Link.ATTENDED and e.end[1] in rank]
        attendees = {who for who, _ in attendances}
        most_recent = {who: min(rank[meeting] for w, meeting in attendances if w == who)
                       for who in attendees}

        people = people_of(edges, meetings)
        assert len(people) == len(attendees) and set(people) == attendees
        ranks = [most_recent[who] for who in people]
        assert ranks == sorted(ranks)
        assert set(people_of(reversed(edges), meetings)) == attendees


class TestWhatAPreparationOpensOn:
    def test_it_says_what_is_known_and_nothing_when_nothing_is(self):
        assert Known("recette").header() == ""
        header = Known("recette", people=("Jacques",), meetings=("r1",)).header()
        assert "Jacques" in header and "recette" in header

    def test_the_header_reads_as_the_person_will_read_it(self):
        known = Known(
            "recette",
            people=("Jacques", "Sophie"),
            meetings=("2026-09-12_recette", "2026-09-05_recette"),
            open_points=("Validation fonctionnelle.", "Jeu de données de test."),
            documents=("cahier-des-charges.pdf",),
            sources=("GREF-42",),
        )
        assert known.header() == (
            "[Ce qui est déjà connu sur « recette »]\n"
            "Réunions précédentes : 2026-09-12_recette, 2026-09-05_recette\n"
            "Personnes qui y participent d'habitude : Jacques, Sophie\n"
            "Resté ouvert :\n"
            "- Validation fonctionnelle.\n"
            "- Jeu de données de test.\n"
            "Documents qui ont servi : cahier-des-charges.pdf\n"
            "Sources suivies : GREF-42\n"
            "\n"
        )

    @mutmut_safe
    @given(KNOWN)
    def test_nothing_is_said_exactly_when_nothing_is_known(self, known):
        assert (known.header() == "") == known.empty

    @mutmut_safe
    @given(KNOWN)
    def test_each_part_is_mentioned_exactly_when_something_is_known_about_it(self, known):
        header = known.header()
        assert ("Réunions précédentes" in header) == bool(known.meetings)
        assert ("Personnes qui y participent" in header) == bool(known.people)
        assert ("Resté ouvert" in header) == bool(known.open_points)
        assert ("Documents qui ont servi" in header) == bool(known.documents)
        assert ("Sources suivies" in header) == bool(known.sources)

    @mutmut_safe
    @given(KNOWN)
    def test_the_subject_opens_and_a_blank_line_closes_whatever_is_known(self, known):
        assume(not known.empty)
        lines = known.header().split("\n")
        assert lines[0] == f"[Ce qui est déjà connu sur « {known.subject} »]"
        assert lines[-2:] == ["", ""]
        assert all(lines[1:-2])

    @mutmut_safe
    @given(KNOWN)
    def test_the_parts_keep_their_order_and_name_everything_known(self, known):
        assume(not known.empty)
        header = known.header()
        headings = ["Réunions précédentes : " + ", ".join(known.meetings),
                    "Personnes qui y participent d'habitude : " + ", ".join(known.people),
                    "Resté ouvert :",
                    "Documents qui ont servi : " + ", ".join(known.documents),
                    "Sources suivies : " + ", ".join(known.sources)]
        parts = (known.meetings, known.people, known.open_points, known.documents, known.sources)
        positions = [header.index(heading) for heading, part in zip(headings, parts, strict=True)
                     if part]
        assert positions == sorted(positions)
        lines = header.split("\n")
        for point in known.open_points:
            assert f"- {point}" in lines
        for point, following in zip(known.open_points, known.open_points[1:], strict=False):
            assert lines.index(f"- {following}") == lines.index(f"- {point}") + 1
