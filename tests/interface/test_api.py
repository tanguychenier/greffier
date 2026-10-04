"""The HTTP door: what it answers, and what it refuses to serve.

A primary adapter like the window, holding no rule of its own. What is checked
here is the door itself -- the token, what is exposed and what deliberately is
not -- and never the chain behind it, which has its own tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from greffier.adapters.configuration import Config  # noqa: E402
from greffier.interface.api import (  # noqa: E402
    _ACCEPTED,
    _JOBS,
    _READ_AS_IS,
    _claim,
    _copy_bounded,
    _process,
    build,
    ensure_a_token,
)

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


def deposit_a_handwritten_part(client, bearer, name, body=b"RIFF"):
    """The multipart body written by hand: httpx percent-encodes a control
    character in the file name, where the parser takes a bare line feed."""
    boundary = "frontiere"
    part = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="enregistrement"; filename="{name}"\r\n'
            "Content-Type: audio/wav\r\n\r\n").encode() + body
    return client.post(
        "/reunions", content=part + f"\r\n--{boundary}--\r\n".encode(),
        headers={**bearer, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def deposit_declaring(client, bearer, content_length):
    """A tiny deposit behind a forged Content-Length; httpx keeps a header given."""
    return client.post("/reunions", headers={**bearer, "Content-Length": str(content_length)},
                       files={"enregistrement": ("point.wav", b"RIFF", "audio/wav")})


def left_in(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def mode_of(file):
    return file.stat().st_mode & 0o777


async def within_seconds(awaitable, *, unless):
    """Fails rather than waits forever: with the outcome of `unless`, a request
    in flight, should it end before the awaited point, else after five seconds.

    A regression in the door must fail the test with a message, not park it on
    an event that only the request would have set.
    """
    waited = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({waited, unless}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
    if waited in done:
        return waited.result()
    waited.cancel()
    assert unless.done(), "nothing happened in 5 s"
    raise AssertionError(f"the request ended before the awaited point: {unless.result()}")


def a_second_of_sound(target):
    """One second of a 440 Hz tone in whatever format the name says, or a skip."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg absent")
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(target)],
        capture_output=True, text=True, check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"ffmpeg cannot write {target.suffix} here: {done.stderr[-120:]}")
    return target


def a_chain_that_notes(handed_over):
    """A chain that only notes what it was handed, in place of wire_up's."""

    class Chain:
        log = None

        def run_chain(self, audio, send):
            handed_over.append(audio)

    return lambda config: Chain()


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


class TestWhatTheChainIsHanded:
    """The voice separation opens the recording through libsndfile, which reads
    five of the nine formats: a container is converted to a .wav first."""

    def test_libsndfile_reads_exactly_the_formats_handed_over_as_they_are(self, tmp_path):
        """The premise, pinned to the installed libsndfile: should it learn a
        container one day, this says which set to move it to."""
        import soundfile

        def readable(suffix):
            try:
                soundfile.info(str(a_second_of_sound(tmp_path / f"son{suffix}")))
            except (RuntimeError, OSError):
                return False
            return True

        assert {s for s in _ACCEPTED if readable(s)} == _READ_AS_IS

    def test_a_deposited_webm_reaches_the_chain_as_a_wav_beside_it(self, config, monkeypatch):
        """Converted in the processing thread, not the handler: decoding takes
        time, and the deposit answers at once. The deposit stays as it came."""
        import soundfile

        handed_over = []
        monkeypatch.setattr("greffier.wiring.wire_up", a_chain_that_notes(handed_over))
        config.paths.recordings.mkdir()
        webm = a_second_of_sound(config.paths.recordings / "point.webm")
        _process(config, webm, "point")
        assert handed_over == [config.paths.recordings / "point.wav"]
        details = soundfile.info(str(handed_over[0]))
        assert (details.channels, details.samplerate) == (1, 16000)
        assert left_in(config.paths.recordings) == ["point.wav", "point.webm"]
        assert _JOBS["point"] == {"phase": "termine", "message": "Compte rendu prêt."}

    def test_the_conversion_is_a_phase_the_client_reads(self, config, monkeypatch, tmp_path):
        seen = []
        monkeypatch.setattr(
            "greffier.application.publish.extract_sound",
            lambda video, destination: seen.append(dict(_JOBS["point"])) or destination,
        )
        monkeypatch.setattr("greffier.wiring.wire_up", a_chain_that_notes([]))
        _process(config, tmp_path / "point.mp4", "point")
        assert seen == [{"phase": "conversion", "message": "Extraction de la piste sonore…"}]

    def test_a_wav_is_handed_over_untouched(self, config, monkeypatch):
        handed_over = []
        monkeypatch.setattr("greffier.wiring.wire_up", a_chain_that_notes(handed_over))
        _process(config, Path("point.wav"), "point")
        assert handed_over == [Path("point.wav")]
        assert _JOBS["point"] == {"phase": "termine", "message": "Compte rendu prêt."}

    def test_a_container_ffmpeg_cannot_open_ends_in_echec(self, config, monkeypatch, tmp_path):
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg absent")
        monkeypatch.setattr("greffier.wiring.wire_up", a_chain_that_notes([]))
        fake = tmp_path / "point.mkv"
        fake.write_bytes(b"not a video")
        _process(config, fake, "point")
        assert _JOBS["point"]["phase"] == "echec"
        assert "extraction du son impossible" in _JOBS["point"]["message"]


class TestWhatNameARecordingMayHave:
    @pytest.mark.parametrize("name", [
        "../x.wav", ".wav", "..", "-x.wav", "a b.wav", "é.wav", "x/y.wav",
        "a" * 122 + ".wav",
    ])
    def test_a_name_that_is_not_a_plain_file_name_is_refused(
            self, config, client, bearer, without_the_chain, name):
        """What a client sends becomes a file name in three folders: 422 first."""
        answered = deposit(client, bearer, name)
        assert answered.status_code == 422, name
        assert "nom" in answered.json()["detail"]
        assert left_in(config.paths.recordings) == []
        assert not without_the_chain

    def test_a_part_without_a_name_is_not_a_recording(
            self, config, client, bearer, without_the_chain):
        """A nameless part arrives as a plain field, and is refused as one."""
        assert deposit(client, bearer, "").status_code == 422
        assert left_in(config.paths.recordings) == []

    def test_a_name_ending_in_a_newline_is_refused_too(
            self, config, client, bearer, without_the_chain):
        """`$` also matches before a final newline: "point\\n.wav" reached the disk."""
        answered = deposit_a_handwritten_part(client, bearer, "point\n.wav")
        assert answered.status_code == 422
        assert "nom" in answered.json()["detail"]
        assert left_in(config.paths.recordings) == []
        assert not without_the_chain

    def test_the_handwritten_part_is_the_one_the_door_takes_plainly(
            self, config, client, bearer, without_the_chain):
        """So that the refusal above is the name's doing, not the body's."""
        assert deposit_a_handwritten_part(client, bearer, "point.wav").status_code == 202
        assert left_in(config.paths.recordings) == ["point.wav"]

    @pytest.mark.parametrize("name", ["point.exe", "point.txt", "point"])
    def test_a_format_the_chain_cannot_read_is_refused_at_the_door(
            self, client, bearer, without_the_chain, name):
        """Refused in a 422 now, not in a job's failure an hour later."""
        answered = deposit(client, bearer, name)
        assert answered.status_code == 422, name
        assert ".wav" in answered.json()["detail"]

    @pytest.mark.parametrize("name", [
        "point.WAV", "point.m4a", "a.b-c_d.webm", "2026-09-12_point.mp4",
    ])
    def test_a_plain_name_in_an_accepted_format_is_taken(
            self, config, client, bearer, without_the_chain, name):
        answered = deposit(client, bearer, name)
        assert answered.status_code == 202, name
        assert answered.json()["identifiant"] == name.rpartition(".")[0]
        assert left_in(config.paths.recordings) == [name]

    @pytest.mark.parametrize("encoded", ["%2E%2E", "-x", "a%20b", "%C3%A9", "point%0A"])
    def test_an_identifier_in_the_path_is_checked_the_same_way(
            self, client, bearer, encoded):
        """Starlette keeps "/" out of a segment; the rest is checked here."""
        for route in (f"/travaux/{encoded}", f"/reunions/{encoded}",
                      f"/reunions/{encoded}/compte-rendu",
                      f"/reunions/{encoded}/transcription"):
            answered = client.get(route, headers=bearer)
            assert answered.status_code == 422, route
            assert answered.json()["detail"] == "identifiant invalide"

    def test_an_identifier_needs_the_token_before_it_is_judged(self, client):
        """401 says nothing about the name: no probing without a token."""
        assert client.get("/travaux/%2E%2E").status_code == 401


class TestARecordingWhoseNameIsTaken:
    def test_the_second_deposit_is_refused_and_the_first_kept(
            self, config, client, bearer, without_the_chain):
        """Overwriting would hand the first client the second meeting's minutes."""
        assert deposit(client, bearer, "point.wav", b"premier").status_code == 202
        answered = deposit(client, bearer, "point.wav", b"second")
        assert answered.status_code == 409
        assert "nom" in answered.json()["detail"]
        assert (config.paths.recordings / "point.wav").read_bytes() == b"premier"
        assert len(without_the_chain) == 1

    def test_the_same_name_in_another_format_is_the_same_name(
            self, config, client, bearer, without_the_chain):
        """The minutes and the transcript are keyed by the stem, not the file."""
        assert deposit(client, bearer, "point.wav").status_code == 202
        assert deposit(client, bearer, "point.m4a").status_code == 409
        assert left_in(config.paths.recordings) == ["point.wav"]

    @pytest.mark.parametrize("first, second", [("a.b.wav", "a.wav"), ("a.wav", "a.b.wav")])
    def test_a_name_that_only_begins_like_another_is_another_name(
            self, config, client, bearer, without_the_chain, first, second):
        """A dot may sit inside a name: "a.b" does not take "a", in either order."""
        assert deposit(client, bearer, first).status_code == 202
        assert deposit(client, bearer, second).status_code == 202
        assert left_in(config.paths.recordings) == sorted([first, second])


class TestANameIsTakenFromTheFirstByte:
    def test_two_deposits_of_one_name_at_once_end_202_and_409_never_one_on_the_other(
            self, config, client, bearer, monkeypatch, without_the_chain):
        """The handler yields to the loop while it copies the body: both deposits
        passed the duplicate check, and the second's move erased the first's file."""
        first_is_reading, let_it_finish = asyncio.Event(), asyncio.Event()

        async def parked_copy(recording, stream, limit_mb):
            """Parks the first copy only: were the second to reach this far, it
            must run through and fail the test, not wait on an event the test
            sets after it returns."""
            if not first_is_reading.is_set():
                first_is_reading.set()
                await let_it_finish.wait()
            await _copy_bounded(recording, stream, limit_mb)

        monkeypatch.setattr("greffier.interface.api._copy_bounded", parked_copy)

        async def post(http, body):
            return await http.post("/reunions", headers=bearer,
                                   files={"enregistrement": ("point.wav", body, "audio/wav")})

        async def race():
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://porte") as http:
                first = asyncio.ensure_future(post(http, b"premier"))
                await within_seconds(first_is_reading.wait(), unless=first)
                second = await asyncio.wait_for(post(http, b"second"), timeout=5)
                let_it_finish.set()
                return await asyncio.wait_for(first, timeout=5), second

        first, second = asyncio.run(race())
        assert (first.status_code, second.status_code) == (202, 409)
        assert (config.paths.recordings / "point.wav").read_bytes() == b"premier"
        assert left_in(config.paths.recordings) == ["point.wav"]

    def test_the_file_system_arbitrates_when_two_claims_meet(self, tmp_path):
        """Under the duplicate check, for handlers that would ever run side by side."""
        _claim(tmp_path / "point.wav")
        with pytest.raises(fastapi.HTTPException) as refused:
            _claim(tmp_path / "point.wav")
        assert refused.value.status_code == 409
        assert (tmp_path / "point.wav").read_bytes() == b""

    def test_a_refused_upload_gives_the_name_back(
            self, config, client, bearer, without_the_chain):
        """413, then the same name again: nothing of the first attempt holds it."""
        config.api.max_upload_mb = 1
        heavy = b"x" * (1 << 20) + b"!"
        assert deposit(client, bearer, "point.wav", heavy).status_code == 413
        assert deposit(client, bearer, "point.wav").status_code == 202


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
