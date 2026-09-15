"""The chain in the rooms a meeting is actually held in.

Everything measured until now was a clean recording: two clear voices, close to
the microphone, in silence. No meeting is like that, and the defect reported in
use -- one person coming out as voice 1, 2, 3 -- happens in the rooms, not in
the silence.

`tools/make_room_cases.py` puts the clean meeting through what a room does to
it. Nothing here needs a corpus or a network: the transformations run on the
samples, so these cases run wherever the tests run.

What this file checks is **how many people the chain believes it heard**, which
is the thing that was wrong. Not the transcription, which depends on the
synthesis and has its own tests.

    pytest -m integration
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.domain.meeting import IDENTIFIABLE_SECONDS
from tests.integration.prerequisites import (
    transcription_is_out_of_reach,
    voices_are_out_of_reach,
)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture(scope="module")
def config() -> Config:
    return Config()


@pytest.fixture(scope="module")
def salles(tmp_path_factory, config):
    """The same meeting, put through four rooms."""
    hors = voices_are_out_of_reach(2) or transcription_is_out_of_reach(config)
    if hors:
        pytest.skip(hors)
    import make_room_cases

    dossier = tmp_path_factory.mktemp("salles")
    from make_meeting import make

    propre = make(dossier / "propre.wav")
    faites = {"propre": propre}
    for nom, fabrique in make_room_cases.CAS.items():
        faites[nom] = fabrique(propre, dossier / f"{nom}.wav")
    return faites


def _voices(config: Config, audio: Path) -> dict[str, float]:
    """What the chain concludes: each voice it keeps, and how long it spoke."""
    from greffier.adapters.diarisation_sherpa import SherpaDiariser
    from greffier.adapters.voiceprints_titanet import TitaNetExtractor
    from greffier.application.render import voiceprints_per_voice
    from greffier.domain import voiceprints as domaine

    diarisation = config.paths.models / "diarisation"
    diariser = SherpaDiariser(
        diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
        diarisation / "nemo_en_titanet_large.onnx",
    )
    extractor = TitaNetExtractor(diarisation / "nemo_en_titanet_large.onnx")
    turns = diariser.segment(audio, None)
    per_voice: dict[str, list] = {}
    for turn in turns:
        per_voice.setdefault(turn.voice, []).append(turn.span)
    membership = domaine.stitch(voiceprints_per_voice(extractor, audio, per_voice))
    spoken: dict[str, float] = {}
    for turn in turns:
        group = membership.get(turn.voice, turn.voice)
        spoken[group] = spoken.get(group, 0.0) + turn.span.duration
    return spoken


@pytest.mark.integration
class TestLaSalleNeFabriquePasDeMonde:
    def test_a_clean_meeting_holds_two_people(self, config, salles):
        assert len(_voices(config, salles["propre"])) == 2

    def test_somebody_leaning_back_stays_one_person(self, config, salles):
        """A voice losing 18 dB mid-meeting cost 0.05 of resemblance to
        itself, enough to become somebody else."""
        assert len(_voices(config, salles["loin"])) == 2

    def test_a_room_with_a_background_holds_two_people(self, config, salles):
        assert len(_voices(config, salles["bruit"])) == 2

    def test_two_people_speaking_at_once_are_still_two(self, config, salles):
        assert len(_voices(config, salles["ensemble"])) == 2

    def test_one_sentence_at_the_end_is_a_voice_but_not_yet_a_person(
        self, config, salles
    ):
        """It exists as a voice, and is not announced as an identified
        person: under six seconds, nothing allows saying so."""
        parle = _voices(config, salles["tard"])
        assert len(parle) == 2
        montrees = [s for s in parle.values() if s >= IDENTIFIABLE_SECONDS]
        assert len(montrees) == 1
