"""The HTTP door: what it answers, and what it refuses to serve.

A primary adapter like the window, holding no rule of its own. What is checked
here is the door itself -- the token, what is exposed and what deliberately is
not -- and never the chain behind it, which has its own tests.
"""

from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from greffier.adapters.configuration import Config  # noqa: E402
from greffier.interface.api import build, ensure_a_token  # noqa: E402

JETON = "un-jeton-pour-les-essais"


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    config.paths.data = tmp_path / "donnees"
    config.api.token = JETON
    (config.paths.data / "reunions").mkdir(parents=True)
    (config.paths.data / "comptes-rendus").mkdir(parents=True)
    (config.paths.data / "transcriptions").mkdir(parents=True)
    return config


@pytest.fixture
def client(config):
    return TestClient(build(config))


@pytest.fixture
def porteur():
    return {"Authorization": f"Bearer {JETON}"}


class TestTheDoorIsShutWithoutAToken:
    def test_health_is_open(self, client):
        """Enough to know the door answers, and no more."""
        answered = client.get("/sante")
        assert answered.status_code == 200
        assert answered.json()["outil"] == "greffier"

    def test_everything_else_is_refused(self, client):
        for route in ("/reunions", "/memoire", "/reunions/x/compte-rendu"):
            assert client.get(route).status_code == 401, route

    def test_a_wrong_token_is_refused(self, client):
        answered = client.get("/reunions", headers={"Authorization": "Bearer non"})
        assert answered.status_code == 401

    def test_with_no_token_configured_nothing_opens(self, config):
        """An empty setting must not mean an open door."""
        config.api.token = ""
        sans = TestClient(build(config))
        assert sans.get("/reunions").status_code == 401


class TestWhatItServes:
    def test_the_minutes_come_back_as_they_were_written(self, config, client, porteur):
        (config.paths.minutes_folder / "reunion.md").write_text(
            "# Compte rendu\n\n## Décisions\n\n- Jeudi.\n", encoding="utf-8")
        answered = client.get("/reunions/reunion/compte-rendu", headers=porteur)
        assert answered.status_code == 200
        assert "Décisions" in answered.text

    def test_a_meeting_that_does_not_exist_says_so(self, client, porteur):
        assert client.get("/reunions/absente", headers=porteur).status_code == 404
        assert client.get(
            "/reunions/absente/compte-rendu", headers=porteur).status_code == 404

    def test_what_earlier_meetings_left_is_served(self, config, client, porteur):
        (config.paths.memory).write_text(json.dumps({
            "identifier": "2026-09-12_reunion", "title": "recette",
            "held_on": "2026-09-12", "decisions": ["Jeudi."],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        answered = client.get("/memoire", headers=porteur)
        assert answered.status_code == 200
        assert answered.json()[0]["decisions"] == ["Jeudi."]


class TestWhatItRefusesToServe:
    def test_the_voice_bank_has_no_route(self, client, porteur):
        """Voice prints are biometric data: they stay on the machine."""
        routes = {getattr(r, "path", "") for r in client.app.routes}
        assert not any("voix" in r or "banque" in r or "empreinte" in r for r in routes)

    def test_no_route_sends_anything_anywhere(self, client):
        """A door that could send the minutes by mail is a door that spams."""
        routes = {getattr(r, "path", "") for r in client.app.routes}
        assert not any("envoi" in r or "courriel" in r for r in routes)


class TestARecordingHandedOver:
    def test_it_answers_at_once_rather_than_in_an_hour(
            self, config, client, porteur, monkeypatch):
        """An hour of transcription is not a request: 202 and an identifier."""
        lances = []
        monkeypatch.setattr(
            "greffier.interface.api.threading.Thread",
            lambda target, args, daemon: type(
                "Faux", (), {"start": lambda self: lances.append(args)})(),
        )
        answered = client.post(
            "/reunions", headers=porteur,
            files={"enregistrement": ("point.wav", b"RIFF----WAVEfmt ", "audio/wav")},
        )
        assert answered.status_code == 202
        assert answered.json()["identifiant"] == "point"
        assert lances, "le traitement doit partir dans un fil"

    def test_the_phases_are_readable_while_it_runs(
            self, config, client, porteur, monkeypatch):
        monkeypatch.setattr(
            "greffier.interface.api.threading.Thread",
            lambda target, args, daemon: type(
                "Faux", (), {"start": lambda self: None})(),
        )
        client.post("/reunions", headers=porteur,
                    files={"enregistrement": ("point.wav", b"RIFF", "audio/wav")})
        answered = client.get("/travaux/point", headers=porteur)
        assert answered.status_code == 200
        assert answered.json()["phase"] == "attente"

    def test_an_unknown_job_says_so(self, client, porteur):
        assert client.get("/travaux/jamais", headers=porteur).status_code == 404


class TestTheToken:
    def test_it_is_written_once_and_kept(self, tmp_path, monkeypatch):
        """A site is configured once; a token reissued at every start is not one."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        config = Config()
        config.api.token = ""
        premier = ensure_a_token(config)
        assert len(premier) > 20
        assert ensure_a_token(config) == premier
