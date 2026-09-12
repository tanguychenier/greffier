"""The index of what the tool knows: one file, rebuilt from everything else."""

from __future__ import annotations

import pytest

from greffier.adapters import graph_sqlite as graphe
from greffier.domain.graph import Edge, Kind, Link, Node


@pytest.fixture
def file(tmp_path):
    fichier = tmp_path / "graphe.sqlite3"
    graphe.write(
        fichier,
        [Node(Kind.MEETING, "2026-09-12_recette"), Node(Kind.MEETING, "2026-09-05_recette"),
         Node(Kind.SUBJECT, "recette"), Node(Kind.PERSON, "Jacques"),
         Node(Kind.PERSON, "Sophie"), Node(Kind.DOCUMENT, "cahier.pdf")],
        [Edge(Link.ABOUT, (Kind.MEETING, "2026-09-12_recette"), (Kind.SUBJECT, "recette")),
         Edge(Link.ABOUT, (Kind.MEETING, "2026-09-05_recette"), (Kind.SUBJECT, "recette")),
         Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"), (Kind.MEETING, "2026-09-12_recette")),
         Edge(Link.ATTENDED, (Kind.PERSON, "Sophie"), (Kind.MEETING, "2026-09-05_recette")),
         Edge(Link.LEFT_OPEN, (Kind.MEETING, "2026-09-12_recette"),
              (Kind.OPEN_POINT, "valider les anomalies")),
         Edge(Link.SUPPLIED, (Kind.DOCUMENT, "cahier.pdf"),
              (Kind.MEETING, "2026-09-12_recette"))],
    )
    return fichier


class TestWhatIsKnownAboutASubject:
    def test_the_meetings_come_back_most_recent_first(self, file):
        assert graphe.known_about(file, "recette").meetings[0] == "2026-09-12_recette"

    def test_the_people_of_those_meetings(self, file):
        """Who usually attends is what fills « attendus » without typing it."""
        assert set(graphe.known_about(file, "recette").people) == {"Jacques", "Sophie"}

    def test_what_was_left_open(self, file):
        assert "valider les anomalies" in graphe.known_about(file, "recette").open_points

    def test_the_documents_that_served(self, file):
        assert "cahier.pdf" in graphe.known_about(file, "recette").documents

    def test_a_subject_nobody_ever_met_about_is_empty(self, file):
        assert graphe.known_about(file, "inconnu").empty

    def test_no_file_is_not_an_error(self, tmp_path):
        assert graphe.known_about(tmp_path / "rien.sqlite3", "recette").empty


class TestForgettingSomebody:
    def test_the_person_and_everything_said_of_them_go(self, file):
        """Article 9 is not a setting: forgetting must forget."""
        assert graphe.forget_person(file, "Sophie") > 0
        assert "Sophie" not in graphe.known_about(file, "recette").people

    def test_the_others_stay(self, file):
        graphe.forget_person(file, "Sophie")
        assert "Jacques" in graphe.known_about(file, "recette").people

    def test_forgetting_somebody_unknown_is_not_an_error(self, file):
        assert graphe.forget_person(file, "Personne") == 0


class TestItIsAnIndexAndNotTheTruth:
    def test_it_can_be_emptied_and_built_again(self, file):
        """A graph one cannot throw away is a graph nobody dares feed."""
        graphe.forget_everything(file)
        assert graphe.known_about(file, "recette").empty
        graphe.write(file, [Node(Kind.SUBJECT, "recette"),
                            Node(Kind.MEETING, "2026-09-12_recette")],
                     [Edge(Link.ABOUT, (Kind.MEETING, "2026-09-12_recette"),
                           (Kind.SUBJECT, "recette"))])
        assert graphe.known_about(file, "recette").meetings

    def test_writing_the_same_fact_twice_says_it_once(self, file):
        graphe.write(file, [Node(Kind.PERSON, "Jacques")],
                     [Edge(Link.ATTENDED, (Kind.PERSON, "Jacques"),
                           (Kind.MEETING, "2026-09-12_recette"))])
        assert graphe.known_about(file, "recette").people.count("Jacques") == 1
