"""Lire et écrire sur un Jira inscrit, et refuser le reste."""

import base64
import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import jira_api
from greffier.domain.sources import Kind, Right, Source

SECRET = "moi@exemple.fr:jeton-atlassian"


def source(droit: Right = Right.LECTURE) -> Source:
    return Source(
        name="suivi", kind=Kind.JIRA, adresse="https://exemple.atlassian.net",
        project="PROJ", droit=droit, token="trousseau:greffier-jira",
    )


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeJira:
    def __init__(self) -> None:
        self.appels: list = []
        self.charge: object = {"issues": []}

    def __call__(self, requete, timeout=None):
        self.appels.append(requete)
        return Response(json.dumps(self.charge).encode("utf-8"))

    @property
    def first_call(self):
        return self.appels[0]


@pytest.fixture
def jira(monkeypatch) -> FakeJira:
    faux = FakeJira()
    monkeypatch.setattr(jira_api.urllib.request, "urlopen", faux)
    return faux


@pytest.fixture
def silent_server(monkeypatch):
    def jamais(*_args, **_options):
        raise AssertionError("aucun appel ne devait partir")

    monkeypatch.setattr(jira_api.urllib.request, "urlopen", jamais)


UNE_DEMANDE = {
    "key": "PROJ-12",
    "fields": {
        "summary": "Reprendre la recette",
        "status": {"name": "En cours"},
        "assignee": {"displayName": "Sophie"},
    },
}


class TestTheCredentials:
    def test_the_secret_carries_the_address_and_the_token(self, jira):
        """Basic demande les deux ; un seul secret est à déposer."""
        jira_api.requests(source(), SECRET)
        expected = base64.b64encode(SECRET.encode()).decode()
        assert jira.first_call.get_header("Authorization") == f"Basic {expected}"

    def test_a_secret_with_no_address_is_reported_plainly(self, silent_server):
        with pytest.raises(jira_api.JiraRefused, match="adresse@exemple.fr"):
            jira_api.requests(source(), "jeton-tout-seul")

    def test_the_account_address_is_not_in_the_register(self):
        """Elle identifie une personne : elle vit dans le secret, pas ici."""
        assert "@" not in source().token


class TestReadingFromJira:
    def test_the_requests_come_back_usable(self, jira):
        jira.charge = {"issues": [UNE_DEMANDE]}
        found = jira_api.requests(source(), SECRET)
        assert found[0].key == "PROJ-12"
        assert found[0].state == "En cours"
        assert found[0].assigne == "Sophie"

    def test_the_web_address_follows_from_the_key(self, jira):
        jira.charge = {"issues": [UNE_DEMANDE]}
        adresse = jira_api.requests(source(), SECRET)[0].adresse
        assert adresse == "https://exemple.atlassian.net/browse/PROJ-12"

    def test_a_request_with_nobody_assigned_breaks_nothing(self, jira):
        jira.charge = {"issues": [{**UNE_DEMANDE, "fields": {"summary": "x"}}]}
        rendue = jira_api.requests(source(), SECRET)[0]
        assert rendue.assigne == "" and rendue.state == ""

    def test_the_line_shows_the_request_at_a_glance(self, jira):
        jira.charge = {"issues": [UNE_DEMANDE]}
        said = jira_api.requests(source(), SECRET)[0].say()
        assert "PROJ-12" in said and "Sophie" in said and "En cours" in said

    def test_the_project_in_the_register_bounds_the_query(self, jira):
        jira_api.requests(source(), SECRET)
        assert "PROJ" in jira.first_call.full_url

    def test_what_is_done_is_left_out_by_default(self, jira):
        jira_api.requests(source(), SECRET)
        assert "statusCategory" in jira.first_call.full_url

    def test_everything_can_be_asked_for(self, jira):
        jira_api.requests(source(), SECRET, ouvertes=False)
        assert "statusCategory" not in jira.first_call.full_url


class TestWritingToJira:
    def test_a_read_only_source_does_not_even_call(self, silent_server):
        with pytest.raises(jira_api.JiraRefused, match="lecture seule"):
            jira_api.create_a_request(source(), SECRET, "Faire la chose")

    def test_an_empty_title_is_refused(self, silent_server):
        with pytest.raises(jira_api.JiraRefused):
            jira_api.create_a_request(source(Right.ECRITURE), SECRET, " ")

    def test_the_created_request_comes_back_with_its_url(self, jira):
        jira.charge = {"key": "PROJ-13"}
        creee = jira_api.create_a_request(
            source(Right.ECRITURE), SECRET, "Reprendre la recette"
        )
        assert creee.key == "PROJ-13"
        assert creee.adresse.endswith("/browse/PROJ-13")
        assert jira.first_call.method == "POST"

    def test_the_body_names_the_registered_project(self, jira):
        jira.charge = {"key": "PROJ-13"}
        jira_api.create_a_request(source(Right.ECRITURE), SECRET, "x")
        envoye = json.loads(jira.first_call.data)
        assert envoye["fields"]["project"]["key"] == "PROJ"

    def test_the_description_leaves_in_document_format(self, jira):
        """Du texte brut est refusé par l'API 3, et l'erreur ne le dit pas."""
        jira.charge = {"key": "PROJ-13"}
        jira_api.create_a_request(
            source(Right.ECRITURE), SECRET, "x", description="parce que"
        )
        decrit = json.loads(jira.first_call.data)["fields"]["description"]
        assert decrit["type"] == "doc"
        assert decrit["content"][0]["content"][0]["text"] == "parce que"

    def test_with_no_description_no_field_is_sent(self, jira):
        jira.charge = {"key": "PROJ-13"}
        jira_api.create_a_request(source(Right.ECRITURE), SECRET, "x")
        assert "description" not in json.loads(jira.first_call.data)["fields"]


class TestWhenItFailsItSaysSo:
    def test_refused_credentials_say_what_to_check(self, monkeypatch):
        def tomber(*_args, **_options):
            raise urllib.error.HTTPError(
                "https://x", 401, "non", {}, BytesIO(b"{}")  # type: ignore[arg-type]
            )

        monkeypatch.setattr(jira_api.urllib.request, "urlopen", tomber)
        with pytest.raises(jira_api.JiraRefused, match="jeton"):
            jira_api.requests(source(), SECRET)

    def test_an_unreachable_server_is_reported_without_falling_over(self, monkeypatch):
        def tomber(*_args, **_options):
            raise urllib.error.URLError("nom introuvable")

        monkeypatch.setattr(jira_api.urllib.request, "urlopen", tomber)
        with pytest.raises(jira_api.JiraRefused, match="injoignable"):
            jira_api.requests(source(), SECRET)

    def test_an_unexpected_answer_is_reported(self, jira):
        jira.charge = ["pas un objet"]
        with pytest.raises(jira_api.JiraRefused):
            jira_api.requests(source(), SECRET)
