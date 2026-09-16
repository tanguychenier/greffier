"""A recording replayed as if the microphone were capturing it.

Asked for on 2026-09-16: the live words did not match, the assistant was
slow, the context seemed lost, and none of it could be reproduced without
holding a meeting. A file in place of the microphone plays the meeting at
its own pace through the very same chain: the chunks, the watch, the live
thread and the assistant see what a microphone would have given them.
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from greffier.adapters.audio_ffmpeg import FfmpegRecorder
from greffier.cli import application

runner = CliRunner()


def _a_second_of_silence(target: Path, seconds: float = 0.6) -> Path:
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * int(16000 * seconds))
    return target


class TestTheInputOfTheRecorder:
    def test_a_recording_stands_in_for_the_microphone(self, tmp_path):
        audio = _a_second_of_silence(tmp_path / "reunion.wav")
        assert FfmpegRecorder(str(audio))._input() == ["-re", "-i", str(audio)]

    def test_a_device_name_stays_a_device(self):
        recorder = FfmpegRecorder("default")
        assert recorder.replays_a_file() is False
        assert "-re" not in recorder._input()

    def test_a_file_that_is_not_there_is_not_replayed(self, tmp_path):
        assert FfmpegRecorder(str(tmp_path / "absent.wav")).replays_a_file() is False

    def test_a_video_may_be_replayed_too(self, tmp_path):
        clip = tmp_path / "visio.mp4"
        clip.write_bytes(b"not really a video, only its name matters here")
        assert FfmpegRecorder(str(clip)).replays_a_file() is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
class TestReplayingFromTheCommandLine:
    @pytest.fixture
    def poste(self, tmp_path, monkeypatch):
        for key in [c for c in __import__("os").environ if c.startswith("GREFFIER_")]:
            monkeypatch.delenv(key)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        data = tmp_path / "donnees"
        settings = tmp_path / "config.toml"
        settings.write_text(
            f'[chemins]\ndonnees = "{data}"\nmodeles = "{tmp_path / "modeles"}"\n'
            '[compte_rendu]\nmoteur = "aucun"\n[direct]\nactif = false\n',
            encoding="utf-8",
        )
        data.mkdir(parents=True)
        return settings, data

    def test_the_file_is_played_to_the_end_and_the_state_comes_back_to_rest(
        self, poste, tmp_path
    ):
        settings, data = poste
        audio = _a_second_of_silence(tmp_path / "reunion.wav")
        answered = runner.invoke(
            application, ["rejouer", str(audio), "--sans-traiter", "--config", str(settings)]
        )
        assert answered.exit_code == 0, answered.stdout
        assert "Rejeu" in answered.stdout
        assert "arrêté" in answered.stdout
        recorded = list((data / "enregistrements").glob("*-rejeu.wav"))
        assert len(recorded) == 1
        with wave.open(str(recorded[0])) as replayed:
            assert replayed.getnframes() > 0
        from greffier.adapters.configuration import Config
        from greffier.wiring import recording

        state = recording(Config.load(settings)).read()
        assert state.phase.value != "enregistrement"

    def test_a_file_that_does_not_exist_is_refused(self, poste, tmp_path):
        settings, _ = poste
        answered = runner.invoke(
            application, ["rejouer", str(tmp_path / "absent.wav"), "--config", str(settings)]
        )
        assert answered.exit_code != 0
