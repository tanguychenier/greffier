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

TOKEN = "un-jeton-pour-les-essais"


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    config.paths.data = tmp_path / "donnees"
    config.api.token = TOKEN
    (config.paths.data / "reunions").mkdir(parents=True)
    (config.paths.data / "comptes-rendus").mkdir(parents=True)
    (config.paths.data / "transcriptions").mkdir(parents=True)
    return config


@pytest.fixture
def client(config):
    return TestClient(build(config))


@pytest.fixture
def bearer():
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def without_the_chain(monkeypatch):
    """The processing never starts: what is checked here is the door."""
    launched = []
    monkeypatch.setattr(
        "greffier.interface.api.threading.Thread",
        lambda target, args, daemon: type(
            "Faux", (), {"start": lambda self: launched.append(args)})(),
    )
    return launched


def deposit(client, bearer, name, body=b"RIFF----WAVEfmt "):
    return client.post("/reunions", headers=bearer,
                       files={"enregistrement": (name, body, "audio/wav")})


def deposit_declaring(client, bearer, content_length):
    """A tiny deposit behind a forged Content-Length; httpx keeps a header given."""
    return client.post("/reunions", headers={**bearer, "Content-Length": str(content_length)},
                       files={"enregistrement": ("point.wav", b"RIFF", "audio/wav")})


def left_in(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def mode_of(file):
    return file.stat().st_mode & 0o777


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
        without = TestClient(build(config))
        assert without.get("/reunions").status_code == 401


class TestWhatItServes:
    def test_the_minutes_come_back_as_they_were_written(self, config, client, bearer):
        (config.paths.minutes_folder / "reunion.md").write_text(
            "# Compte rendu\n\n## Décisions\n\n- Jeudi.\n", encoding="utf-8")
        answered = client.get("/reunions/reunion/compte-rendu", headers=bearer)
        assert answered.status_code == 200
        assert "Décisions" in answered.text

    def test_a_meeting_that_does_not_exist_says_so(self, client, bearer):
        assert client.get("/reunions/absente", headers=bearer).status_code == 404
        assert client.get(
            "/reunions/absente/compte-rendu", headers=bearer).status_code == 404

    def test_what_earlier_meetings_left_is_served(self, config, client, bearer):
        (config.paths.memory).write_text(json.dumps({
            "identifier": "2026-09-12_reunion", "title": "recette",
            "held_on": "2026-09-12", "decisions": ["Jeudi."],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        answered = client.get("/memoire", headers=bearer)
        assert answered.status_code == 200
        assert answered.json()[0]["decisions"] == ["Jeudi."]


class TestWhatItRefusesToServe:
    def test_the_voice_bank_has_no_route(self, client, bearer):
        """Voice prints are biometric data: they stay on the machine."""
        routes = {getattr(r, "path", "") for r in client.app.routes}
        assert not any("voix" in r or "banque" in r or "empreinte" in r for r in routes)

    def test_no_route_sends_anything_anywhere(self, client):
        """A door that could send the minutes by mail is a door that spams."""
        routes = {getattr(r, "path", "") for r in client.app.routes}
        assert not any("envoi" in r or "courriel" in r for r in routes)


class TestARecordingHandedOver:
    def test_it_answers_at_once_rather_than_in_an_hour(
            self, config, client, bearer, monkeypatch):
        """An hour of transcription is not a request: 202 and an identifier."""
        lances = []
        monkeypatch.setattr(
            "greffier.interface.api.threading.Thread",
            lambda target, args, daemon: type(
                "Faux", (), {"start": lambda self: lances.append(args)})(),
        )
        answered = client.post(
            "/reunions", headers=bearer,
            files={"enregistrement": ("point.wav", b"RIFF----WAVEfmt ", "audio/wav")},
        )
        assert answered.status_code == 202
        assert answered.json()["identifiant"] == "point"
        assert lances, "le traitement doit partir dans un fil"

    def test_the_phases_are_readable_while_it_runs(
            self, config, client, bearer, monkeypatch):
        monkeypatch.setattr(
            "greffier.interface.api.threading.Thread",
            lambda target, args, daemon: type(
                "Faux", (), {"start": lambda self: None})(),
        )
        client.post("/reunions", headers=bearer,
                    files={"enregistrement": ("point.wav", b"RIFF", "audio/wav")})
        answered = client.get("/travaux/point", headers=bearer)
        assert answered.status_code == 200
        assert answered.json()["phase"] == "attente"

    def test_an_unknown_job_says_so(self, client, bearer):
        assert client.get("/travaux/jamais", headers=bearer).status_code == 404


class TestHowMuchTheDoorTakesIn:
    ONE_MIB = 1 << 20

    def test_a_body_one_byte_over_the_limit_is_refused_and_leaves_nothing(
            self, config, client, bearer, without_the_chain):
        """A refused upload must not fill the disk one temporary at a time."""
        config.api.max_upload_mb = 1
        answered = deposit(client, bearer, "lourd.wav", b"x" * self.ONE_MIB + b"!")
        assert answered.status_code == 413
        assert "1 Mio" in answered.json()["detail"]
        assert left_in(config.paths.recordings) == []
        assert not without_the_chain, "nothing to process when nothing was kept"

    def test_a_body_at_the_limit_is_taken_whole(
            self, config, client, bearer, without_the_chain):
        """Its Content-Length is past the limit by the multipart framing: the
        header cut leaves that margin, and the handler draws the exact line."""
        config.api.max_upload_mb = 1
        answered = deposit(client, bearer, "plein.wav", b"x" * self.ONE_MIB)
        assert answered.status_code == 202
        assert left_in(config.paths.recordings) == ["plein.wav"]
        assert (config.paths.recordings / "plein.wav").stat().st_size == self.ONE_MIB

    def test_a_declared_length_past_the_limit_is_refused_with_nothing_read(
            self, config, client, bearer, without_the_chain):
        """The body is parsed before any route code runs, so the first cut is
        on the header: a tiny body behind a forged length never reaches the
        handler, which would have taken it."""
        config.api.max_upload_mb = 1
        answered = deposit_declaring(client, bearer, 3 * self.ONE_MIB)
        assert answered.status_code == 413
        assert "1 Mio" in answered.json()["detail"]
        assert left_in(config.paths.recordings) == []
        assert not without_the_chain

    def test_a_declared_length_within_one_chunk_of_the_limit_reaches_the_handler(
            self, config, client, bearer, without_the_chain):
        config.api.max_upload_mb = 1
        assert deposit_declaring(client, bearer, 2 * self.ONE_MIB).status_code == 202

    def test_without_the_token_a_declared_length_is_told_nothing(self, config, client):
        """401 before 413: the limit is not for whoever knocks."""
        config.api.max_upload_mb = 1
        assert deposit_declaring(client, {}, 3 * self.ONE_MIB).status_code == 401

    def test_a_deposited_recording_is_readable_like_any_file_the_tool_writes(
            self, config, client, bearer, without_the_chain):
        """`tempfile` would have made it 0600: another tool a site points at the
        folder, under another user, could not have read it."""
        deposit(client, bearer, "point.wav")
        plainly_written = config.paths.recordings / "temoin.wav"
        plainly_written.write_bytes(b"RIFF")
        assert mode_of(config.paths.recordings / "point.wav") == mode_of(plainly_written)

    def test_the_limit_is_a_setting_with_a_french_key(self):
        from greffier.adapters.configuration import SECTIONS

        assert Config(api={"taille_max_mo": 12}).api.max_upload_mb == 12
        assert Config().api.max_upload_mb == 4096
        assert "taille_max_mo" in SECTIONS["api"]


class TestTheToken:
    def test_it_is_written_once_and_kept(self, tmp_path, monkeypatch):
        """A site is configured once; a token reissued at every start is not one."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        config = Config()
        config.api.token = ""
        first = ensure_a_token(config)
        assert len(first) > 20
        assert ensure_a_token(config) == first
