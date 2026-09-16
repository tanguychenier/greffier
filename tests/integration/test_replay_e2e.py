"""A whole meeting replayed through the product, from the microphone's seat.

`greffier rejouer` plays a recording as the microphone would: the encoder
writes the chunks at the recording's own pace, the live thread transcribes
the slices as they come, and the final processing follows. This is the end
to end test the tool lacked: everything a meeting exercises, without holding
one. Slow (the file plays in real time) and dependent on the models, hence
"integration".

    pytest -m integration tests/integration/test_replay_e2e.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from greffier.adapters.configuration import Config
from greffier.cli import application
from tests.integration.prerequisites import (
    transcription_is_out_of_reach,
    voices_are_out_of_reach,
)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture(scope="module")
def meeting(tmp_path_factory) -> Path:
    out_of_reach = voices_are_out_of_reach(2)
    if out_of_reach:
        pytest.skip(out_of_reach)
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg absent")
    from make_meeting import make

    return make(tmp_path_factory.mktemp("audio") / "reunion.wav")


@pytest.fixture(scope="module")
def replayed(meeting: Path, tmp_path_factory) -> tuple[Path, Path]:
    """The meeting replayed once, live thread on, then processed; reused by every test."""
    installed = Config()
    out_of_reach = transcription_is_out_of_reach(installed)
    if out_of_reach:
        pytest.skip(out_of_reach)
    home = tmp_path_factory.mktemp("poste")
    data = home / "donnees"
    settings = home / "config.toml"
    settings.write_text(
        f'[chemins]\ndonnees = "{data}"\nmodeles = "{installed.paths.models}"\n'
        '[compte_rendu]\nmoteur = "aucun"\n'
        '[direct]\nactif = true\nperiode = 5\n'
        '[assistant]\nvoix = "aucun"\n',
        encoding="utf-8",
    )
    data.mkdir(parents=True)
    answered = runner.invoke(
        application, ["rejouer", str(meeting), "--sans-envoi", "--config", str(settings)]
    )
    assert answered.exit_code == 0, answered.stdout
    return settings, data


class TestWhatAReplayedMeetingLeavesBehind:
    def test_the_recording_is_the_meeting_s_length(self, replayed, meeting):
        import soundfile as sf

        _, data = replayed
        recorded = list((data / "enregistrements").glob("*-rejeu.wav"))
        assert len(recorded) == 1
        assert abs(sf.info(str(recorded[0])).duration - sf.info(str(meeting)).duration) < 2.0

    def test_the_live_thread_heard_words_while_it_played(self, replayed):
        _, data = replayed
        threads = list((data / "direct").glob("*.jsonl"))
        assert threads, "no live thread was written"
        turns = [
            json.loads(line)
            for line in threads[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        spoken = [t for t in turns if t.get("genre") == "tour" and t.get("texte")]
        assert spoken, "the live thread carried no transcribed turn"
        assert sum(len(t["texte"].split()) for t in spoken) > 20

    def test_the_final_processing_followed(self, replayed):
        _, data = replayed
        meetings = list((data / "reunions").glob("*-rejeu.json"))
        assert len(meetings) == 1
        kept = json.loads(meetings[0].read_text(encoding="utf-8"))
        assert len(kept.get("repliques", [])) >= 3
        assert (data / "transcriptions" / f"{meetings[0].stem}.txt").exists()
