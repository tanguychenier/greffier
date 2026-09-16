"""What the assistant answers from: the documents, the web, the company's sources.

Four scenarios from the project manager's seat, each through the product's
own path (`assistant_of`, `_live_material`, `AssistantSettings.answer`) and
the real model behind Claude Code, so that what is checked is what a meeting
would hear. Skipped where `claude` is not installed or not signed in.

    pytest -m integration tests/integration/test_context_scenarios.py
"""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from greffier.adapters import attachments_file
from greffier.adapters.configuration import Config
from greffier.adapters.system_diagnostic import claude_signed_in
from greffier.domain.participation import Because, Opening

pytestmark = pytest.mark.integration

MEETING = "2026-09-16_10h00_recette"
THREAD = (
    "Jacques : Bonjour à tous, on fait le point sur la recette.\n"
    "Sophie : Le déploiement en préproduction est terminé depuis vendredi.\n"
)


class Voice:
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> bool:
        self.said.append(text)
        return True

    def is_speaking(self) -> bool:
        return False

    def go_quiet(self) -> None:
        pass


class Thread:
    def rendered(self) -> str:
        return THREAD


class Follower:
    thread = Thread()


class GitLab(BaseHTTPRequestHandler):
    """A GitLab that knows one project and two open tickets."""

    def do_GET(self) -> None:  # noqa: N802 -- the name is the protocol's
        if self.headers.get("PRIVATE-TOKEN") != "secret-d-essai":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps([
            {"iid": 12, "title": "Facturation en double sur l'avoir", "state": "opened",
             "web_url": "http://gitlab.local/i/12", "assignee": {"name": "Maud"},
             "labels": ["bug"]},
            {"iid": 15, "title": "Export CSV des règlements", "state": "opened",
             "web_url": "http://gitlab.local/i/15", "assignee": None, "labels": []},
        ]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def gitlab():
    server = HTTPServer(("127.0.0.1", 0), GitLab)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    if shutil.which("claude") is None or not claude_signed_in():
        pytest.skip("claude absent ou non connecté")
    return tmp_path_factory.mktemp("poste")


def _config(home: Path, monkeypatch, web: bool = False) -> Config:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    config = Config()
    config.paths.data = home / "donnees"
    config.assistant.active = True
    config.assistant.voice = "aucun"
    config.conversation.recherche_web = web
    return config


def _her(config: Config):
    from greffier.cli import _live_material
    from greffier.wiring import assistant_of

    lui = assistant_of(config, MEETING)
    assert lui is not None and lui.cerveau is not None
    lui.voice = Voice()
    lui.context = _live_material(config, MEETING, Follower())
    lui.manners.creux_minimal = 0.0
    return lui


def _asked(lui, question: str) -> str:
    remark = lui.answer(Opening(because=Because.APPELE, remark=question, born_at=1.0), 2.0)
    return remark.remark


def _registry(config: Config, adresse: str) -> None:
    config.paths.sources.parent.mkdir(parents=True, exist_ok=True)
    config.paths.sources.write_text(
        '[[sources]]\nnom = "recherche"\ngenre = "gitlab"\n'
        f'adresse = "{adresse}"\nprojet = "equipe/outil"\n'
        'jeton = "GREFFIER_GITLAB_JETON_D_ESSAI"\n',
        encoding="utf-8",
    )


class TestADocumentHandedOverIsUsed:
    def test_she_answers_from_the_document_and_names_it(self, home, monkeypatch):
        config = _config(home, monkeypatch)
        attachments_file.write(config.paths.pieces, MEETING, "budget",
                               "Budget du lot 2 : 42 000 euros hors taxes, validé le 3 septembre.")
        lui = _her(config)
        try:
            answer = _asked(lui, "quel est le budget du lot 2 ?")
        finally:
            lui.cerveau.close()
        lowered = answer.lower()
        assert "42" in lowered or "quarante-deux" in lowered, answer
        assert "budget" in lowered or "document" in lowered, answer


class TestTheCompanySources:
    def test_without_a_token_she_says_she_has_no_access_and_asks_for_it(
        self, home, monkeypatch, gitlab
    ):
        monkeypatch.delenv("GREFFIER_GITLAB_JETON_D_ESSAI", raising=False)
        config = _config(home, monkeypatch)
        _registry(config, gitlab)
        lui = _her(config)
        try:
            answer = _asked(lui, "quels tickets sont ouverts sur GitLab ?")
        finally:
            lui.cerveau.close()
        lowered = answer.lower()
        assert "jeton" in lowered or "accès" in lowered, answer
        assert "facturation" not in lowered, "no ticket invented"

    def test_with_a_token_she_reads_the_tickets_and_names_the_source(
        self, home, monkeypatch, gitlab
    ):
        monkeypatch.setenv("GREFFIER_GITLAB_JETON_D_ESSAI", "secret-d-essai")
        config = _config(home, monkeypatch)
        _registry(config, gitlab)
        lui = _her(config)
        try:
            answer = _asked(lui, "quels tickets sont ouverts sur GitLab ?")
        finally:
            lui.cerveau.close()
        lowered = answer.lower()
        assert "facturation" in lowered or "export" in lowered, answer
        assert "gitlab" in lowered, answer


class TestTheWeb:
    def test_a_fact_outside_the_meeting_is_looked_up_and_its_source_named(
        self, home, monkeypatch
    ):
        config = _config(home, monkeypatch, web=True)
        lui = _her(config)
        searched: list[int] = []
        lui.cerveau.on_search = lambda: searched.append(1)
        try:
            answer = _asked(
                lui, "quelle est la dernière version stable de Python à ce jour ?"
            )
        finally:
            lui.cerveau.close()
        assert searched, f"no search was made: {answer!r}"
        lowered = answer.lower()
        marks = ("d'après", "selon", "site", "documentation")
        assert any(mark in lowered for mark in marks), answer
