"""What the registered outside sources hand the assistant, token or no token."""

from __future__ import annotations

import pytest

from greffier.application.company_sources import (
    HEADER,
    NO_TOKEN,
    Reading,
    Sources,
    material,
    read_all,
)
from greffier.domain.sources import Kind, Registry, Source


def gitlab(name: str = "recherche", token: str = "GREFFIER_GITLAB_JETON") -> Source:
    return Source(name=name, kind=Kind.GITLAB, address="https://gitlab.example.fr",
                  project="equipe/outil", token=token)


def jira(name: str = "suivi") -> Source:
    return Source(name=name, kind=Kind.JIRA, address="https://exemple.atlassian.net",
                  project="PROJ", token="GREFFIER_JIRA_JETON")


class TestReadingEverySource:
    def test_a_source_with_a_token_is_read_by_its_own_kind(self):
        asked = []

        def tickets(source, token):
            asked.append(("gitlab", source.name, token))
            return ["#12 Facturation en double, Maud (opened)"]

        def requests(source, token):
            asked.append(("jira", source.name, token))
            return ["PROJ-7 Recette (À faire)"]

        readings = read_all(Registry([gitlab(), jira()]), lambda s: "secret", tickets, requests)
        assert [r.lines for r in readings] == [
            ("#12 Facturation en double, Maud (opened)",), ("PROJ-7 Recette (À faire)",)
        ]
        assert asked == [("gitlab", "recherche", "secret"), ("jira", "suivi", "secret")]

    def test_a_source_without_a_token_is_named_and_not_called(self):
        readings = read_all(Registry([gitlab()]), lambda s: "",
                            lambda s, t: pytest.fail("called without a token"),
                            lambda s, t: [])
        assert readings[0].readable is False
        assert readings[0].trouble == NO_TOKEN

    def test_a_source_that_refuses_says_so_without_stopping_the_others(self):
        def refuses(source, token):
            raise RuntimeError("jeton refusé sur « recherche » (401)")

        readings = read_all(Registry([gitlab(), jira()]), lambda s: "x", refuses,
                            lambda s, t: ["PROJ-7 Recette (À faire)"])
        assert "jeton refusé" in readings[0].trouble
        assert readings[1].lines == ("PROJ-7 Recette (À faire)",)

    def test_no_source_registered_gives_nothing(self):
        assert read_all(Registry([]), lambda s: "x", lambda s, t: [], lambda s, t: []) == []


class TestWhatTheAssistantReads:
    def test_the_tickets_are_listed_under_their_source(self):
        text = material([Reading(gitlab(), lines=("#12 Facturation en double (opened)",))])
        assert text.startswith(HEADER)
        assert "Source « recherche » (gitlab, projet equipe/outil), 1 ouvert(s) :" in text
        assert "- #12 Facturation en double (opened)" in text

    def test_a_missing_token_is_said_with_where_it_goes(self):
        text = material([Reading(gitlab(), trouble=NO_TOKEN)])
        assert "aucun jeton disponible" in text
        assert "trousseau" in text and "greffier sources" in text

    def test_nothing_open_is_said_as_such(self):
        assert "rien d'ouvert" in material([Reading(jira())])

    def test_no_reading_gives_no_text_at_all(self):
        assert material([]) == ""

    def test_the_material_is_bounded(self):
        many = tuple(f"#{n} Ticket numéro {n}, un titre assez long (opened)" for n in range(200))
        text = material([Reading(gitlab(), lines=many)], at_most=1000)
        assert len(text) <= 1000 + len(HEADER) + 1


class TestTheSourcesAreNotReadAtEveryQuestion:
    def test_read_once_then_again_when_stale(self):
        clock = {"now": 0.0}
        calls = []

        def read():
            calls.append(clock["now"])
            return [Reading(gitlab(), lines=("#1 Un (opened)",))]

        sources = Sources(read, fresh_for=120.0, clock=lambda: clock["now"])
        assert "#1 Un" in sources.material()
        clock["now"] = 60.0
        sources.material()
        assert calls == [0.0]
        clock["now"] = 121.0
        sources.material()
        assert calls == [0.0, 121.0]

    def test_a_reading_that_breaks_costs_no_answer(self):
        def breaks():
            raise OSError("no network")

        assert Sources(breaks).material() == ""
