"""Lire et écrire sur un Jira inscrit, et refuser le reste."""

import base64
import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import jira_api
from greffier.domain.sources import Kind, Right, Source

SECRET = "moi@exemple.fr:jeton-atlassian"


def source(right: Right = Right.READING) -> Source:
    return Source(
        name="suivi", kind=Kind.JIRA, address="https://exemple.atlassian.net",
        project="PROJ", right=right, token="trousseau:greffier-jira",
    )


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeJira:
    def __init__(self) -> None:
        self.calls: list = []
        self.charge: object = {"issues": []}

    def __call__(self, the_request, timeout=None):
        self.calls.append(the_request)
        return Response(json.dumps(self.charge).encode("utf-8"))

    @property
    def first_call(self):
        return self.calls[0]


@pytest.fixture
def jira(monkeypatch) -> FakeJira:
    wrong = FakeJira()
    monkeypatch.setattr(jira_api.urllib.request, "urlopen", wrong)
    return wrong


@pytest.fixture
def silent_server(monkeypatch):
    def never(*_args, **_options):
        raise AssertionError("aucun appel ne devait partir")

    monkeypatch.setattr(jira_api.urllib.request, "urlopen", never)


A_REQUEST = {
    "key": "PROJ-12",
    "fields": {
        "summary": "Reprendre la recette",
        "status": {"name": "En cours"},
        "assignee": {"displayName": "Sophie"},
    },
}


class TestTheCredentials:
    def test_the_secret_carries_the_address_and_the_token(self, jira):
        """Basic asks for both; a single secret is to be stored."""
        jira_api.requests(source(), SECRET)
        expected = base64.b64encode(SECRET.encode()).decode()
        assert jira.first_call.get_header("Authorization") == f"Basic {expected}"

    def test_a_secret_with_no_address_is_reported_plainly(self, silent_server):
        with pytest.raises(jira_api.JiraRefused, match="adresse@exemple.fr"):
            jira_api.requests(source(), "jeton-tout-seul")

    def test_the_account_address_is_not_in_the_register(self):
        """It identifies a person: it lives in the secret, not here."""
        assert "@" not in source().token


class TestReadingFromJira:
    def test_the_requests_come_back_usable(self, jira):
        jira.charge = {"issues": [A_REQUEST]}
        found = jira_api.requests(source(), SECRET)
        assert found[0].key == "PROJ-12"
        assert found[0].state == "En cours"
        assert found[0].assignee == "Sophie"

    def test_the_web_address_follows_from_the_key(self, jira):
        jira.charge = {"issues": [A_REQUEST]}
        address = jira_api.requests(source(), SECRET)[0].address
        assert address == "https://exemple.atlassian.net/browse/PROJ-12"

    def test_a_request_with_nobody_assigned_breaks_nothing(self, jira):
        jira.charge = {"issues": [{**A_REQUEST, "fields": {"summary": "x"}}]}
        returned = jira_api.requests(source(), SECRET)[0]
        assert returned.assignee == "" and returned.state == ""

    def test_the_line_shows_the_request_at_a_glance(self, jira):
        jira.charge = {"issues": [A_REQUEST]}
        said = jira_api.requests(source(), SECRET)[0].say()
        assert "PROJ-12" in said and "Sophie" in said and "En cours" in said

    def test_the_project_in_the_register_bounds_the_query(self, jira):
        jira_api.requests(source(), SECRET)
        assert "PROJ" in jira.first_call.full_url

    def test_what_is_done_is_left_out_by_default(self, jira):
        jira_api.requests(source(), SECRET)
        assert "statusCategory" in jira.first_call.full_url

    def test_everything_can_be_asked_for(self, jira):
        jira_api.requests(source(), SECRET, open_ones=False)
        assert "statusCategory" not in jira.first_call.full_url


class TestWritingToJira:
    def test_a_read_only_source_does_not_even_call(self, silent_server):
        with pytest.raises(jira_api.JiraRefused, match="lecture seule"):
            jira_api.create_a_request(source(), SECRET, "Faire la chose")

    def test_an_empty_title_is_refused(self, silent_server):
        with pytest.raises(jira_api.JiraRefused):
            jira_api.create_a_request(source(Right.WRITING), SECRET, " ")

    def test_the_created_request_comes_back_with_its_url(self, jira):
        jira.charge = {"key": "PROJ-13"}
        created = jira_api.create_a_request(
            source(Right.WRITING), SECRET, "Reprendre la recette"
        )
        assert created.key == "PROJ-13"
        assert created.address.endswith("/browse/PROJ-13")
        assert jira.first_call.method == "POST"

    def test_the_body_names_the_registered_project(self, jira):
        jira.charge = {"key": "PROJ-13"}
        jira_api.create_a_request(source(Right.WRITING), SECRET, "x")
        sent = json.loads(jira.first_call.data)
        assert sent["fields"]["project"]["key"] == "PROJ"

    def test_the_description_leaves_in_document_format(self, jira):
        """Raw text is refused by API 3, and the error does not say so."""
        jira.charge = {"key": "PROJ-13"}
        jira_api.create_a_request(
            source(Right.WRITING), SECRET, "x", description="parce que"
        )
        describes = json.loads(jira.first_call.data)["fields"]["description"]
        assert describes["type"] == "doc"
        assert describes["content"][0]["content"][0]["text"] == "parce que"

    def test_with_no_description_no_field_is_sent(self, jira):
        jira.charge = {"key": "PROJ-13"}
        jira_api.create_a_request(source(Right.WRITING), SECRET, "x")
        assert "description" not in json.loads(jira.first_call.data)["fields"]


class TestWhenItFailsItSaysSo:
    def test_refused_credentials_say_what_to_check(self, monkeypatch):
        def fall(*_args, **_options):
            raise urllib.error.HTTPError(
                "https://x", 401, "non", {}, BytesIO(b"{}")  # type: ignore[arg-type]
            )

        monkeypatch.setattr(jira_api.urllib.request, "urlopen", fall)
        with pytest.raises(jira_api.JiraRefused, match="jeton"):
            jira_api.requests(source(), SECRET)

    def test_an_unreachable_server_is_reported_without_falling_over(self, monkeypatch):
        def fall(*_args, **_options):
            raise urllib.error.URLError("nom introuvable")

        monkeypatch.setattr(jira_api.urllib.request, "urlopen", fall)
        with pytest.raises(jira_api.JiraRefused, match="injoignable"):
            jira_api.requests(source(), SECRET)

    def test_an_unexpected_answer_is_reported(self, jira):
        jira.charge = ["pas un objet"]
        with pytest.raises(jira_api.JiraRefused):
            jira_api.requests(source(), SECRET)
