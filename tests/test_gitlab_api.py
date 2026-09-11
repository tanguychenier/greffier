"""Lire et écrire sur un GitLab inscrit, et refuser le reste."""

import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import gitlab_api
from greffier.domain.sources import Kind, Right, Source


def source(droit: Right = Right.LECTURE) -> Source:
    return Source(
        name="recherche", kind=Kind.GITLAB,
        adresse="https://gitlab.example.fr", project="equipe/outil",
        droit=droit, token="GREFFIER_GITLAB_JETON",
    )


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeGitLab:
    """Un GitLab qui garde ce qu'on lui envoie : l'adresse et le corps comptent."""

    def __init__(self) -> None:
        self.appels: list = []
        self.charge: object = []

    def __call__(self, requete, timeout=None):
        self.appels.append(requete)
        return Response(json.dumps(self.charge).encode("utf-8"))

    @property
    def first_call(self):
        return self.appels[0]


@pytest.fixture
def gitlab(monkeypatch) -> FakeGitLab:
    faux = FakeGitLab()
    monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", faux)
    return faux


@pytest.fixture
def silent_server(monkeypatch):
    """Aucun appel ne doit partir : le refus se décide avant le réseau."""
    def jamais(*_args, **_options):
        raise AssertionError("aucun appel ne devait partir")

    monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", jamais)


def fail_to_answer(monkeypatch, code: int) -> None:
    def tomber(*_args, **_options):
        raise urllib.error.HTTPError(
            "https://x", code, "non", {}, BytesIO(b'{"message":"non"}')  # type: ignore[arg-type]
        )

    monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", tomber)


UN_TICKET = {
    "iid": 42, "title": "Corriger l'envoi", "state": "opened",
    "web_url": "https://gitlab.example.fr/equipe/outil/-/issues/42",
    "assignee": {"name": "Sophie"}, "labels": ["recette"],
}


class TestReadingFromGitLab:
    def test_the_tickets_come_back_usable(self, gitlab):
        gitlab.charge = [UN_TICKET]
        found = gitlab_api.tickets(source(), "glpat-x")
        assert found[0].number == 42
        assert found[0].assigne == "Sophie"
        assert found[0].etiquettes == ("recette",)

    def test_a_ticket_with_nobody_assigned_breaks_nothing(self, gitlab):
        """GitLab rend « assignee: null », pas un objet vide."""
        gitlab.charge = [{**UN_TICKET, "assignee": None}]
        assert gitlab_api.tickets(source(), "glpat-x")[0].assigne == ""

    def test_the_line_shows_the_ticket_at_a_glance(self, gitlab):
        gitlab.charge = [UN_TICKET]
        said = gitlab_api.tickets(source(), "glpat-x")[0].say()
        assert "#42" in said and "Sophie" in said and "recette" in said

    def test_the_project_in_the_register_bounds_the_call(self, gitlab):
        """La portée vient du registre, jamais de la phrase tapée."""
        gitlab_api.tickets(source(), "glpat-x")
        assert "equipe%2Foutil" in gitlab.first_call.full_url

    def test_the_token_travels_in_a_header_not_in_the_url(self, gitlab):
        gitlab_api.tickets(source(), "glpat-secret")
        assert gitlab.first_call.get_header("Private-token") == "glpat-secret"
        assert "glpat-secret" not in gitlab.first_call.full_url

    def test_only_the_open_ones_are_asked_for_by_default(self, gitlab):
        gitlab_api.tickets(source(), "glpat-x")
        assert "state=opened" in gitlab.first_call.full_url

    def test_a_search_term_is_passed_on(self, gitlab):
        gitlab_api.tickets(source(), "glpat-x", cherche="envoi")
        assert "search=envoi" in gitlab.first_call.full_url

    def test_reading_asks_for_no_write_right(self, gitlab):
        assert gitlab_api.tickets(source(Right.LECTURE), "glpat-x") == []

    def test_the_merge_requests_read_too(self, gitlab):
        gitlab.charge = [UN_TICKET]
        found = gitlab_api.join_requests(source(), "glpat-x")
        assert "merge_requests" in gitlab.first_call.full_url
        assert found[0].number == 42


class TestWritingToGitLab:
    def test_a_read_only_source_does_not_even_call(self, silent_server):
        with pytest.raises(gitlab_api.GitLabRefused, match="lecture seule"):
            gitlab_api.create_a_ticket(source(), "glpat-x", "Faire la chose")

    def test_commenting_is_a_write(self, silent_server):
        """Un commentaire notifie des gens et reste attaché à leur travail."""
        with pytest.raises(gitlab_api.GitLabRefused, match="lecture seule"):
            gitlab_api.comment(source(), "glpat-x", 42, "vu")

    def test_an_empty_title_is_refused(self, silent_server):
        with pytest.raises(gitlab_api.GitLabRefused):
            gitlab_api.create_a_ticket(source(Right.ECRITURE), "glpat-x", "  ")

    def test_an_empty_comment_is_refused(self, silent_server):
        with pytest.raises(gitlab_api.GitLabRefused):
            gitlab_api.comment(source(Right.ECRITURE), "glpat-x", 42, "   ")

    def test_the_created_ticket_comes_back_with_its_url(self, gitlab):
        """Une écriture dont on ne montre pas le résultat n'est pas vérifiable."""
        gitlab.charge = UN_TICKET
        cree = gitlab_api.create_a_ticket(
            source(Right.ECRITURE), "glpat-x", "Corriger l'envoi"
        )
        assert cree.number == 42
        assert cree.adresse.endswith("/issues/42")
        assert gitlab.first_call.method == "POST"

    def test_the_body_carries_the_title_given(self, gitlab):
        gitlab.charge = UN_TICKET
        gitlab_api.create_a_ticket(source(Right.ECRITURE), "glpat-x", "Un titre")
        assert json.loads(gitlab.first_call.data)["title"] == "Un titre"

    def test_a_comment_returns_the_url_of_the_ticket(self, gitlab):
        gitlab.charge = {"id": 7}
        rendered = gitlab_api.comment(source(Right.ECRITURE), "glpat-x", 42, "vu")
        assert rendered.endswith("/equipe/outil/-/issues/42")
        assert gitlab.first_call.method == "POST"


class TestWhenItFailsItSaysSo:
    def test_a_refused_token_names_the_scope_to_check(self, monkeypatch):
        fail_to_answer(monkeypatch, 401)
        with pytest.raises(gitlab_api.GitLabRefused, match="read_api"):
            gitlab_api.tickets(source(), "glpat-perime")

    def test_a_missing_project_says_a_private_one_looks_the_same(self, monkeypatch):
        fail_to_answer(monkeypatch, 404)
        with pytest.raises(gitlab_api.GitLabRefused, match="privé"):
            gitlab_api.tickets(source(), "glpat-x")

    def test_an_unreachable_server_is_reported_without_falling_over(self, monkeypatch):
        def tomber(*_args, **_options):
            raise urllib.error.URLError("nom introuvable")

        monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", tomber)
        with pytest.raises(gitlab_api.GitLabRefused, match="injoignable"):
            gitlab_api.tickets(source(), "glpat-x")

    def test_an_unexpected_answer_is_reported(self, gitlab):
        gitlab.charge = {"pas": "une liste"}
        with pytest.raises(gitlab_api.GitLabRefused):
            gitlab_api.tickets(source(), "glpat-x")
