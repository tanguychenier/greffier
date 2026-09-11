"""The traps already met, replayed through the real chain.

`tools/make_hard_cases.py` builds one recording per defect seen in a real
meeting or made possible by the design. This file puts them through the real
chain — segmentation, recognition, name attribution — rather than through
doubles, to prove the defect stays fixed.

Slow, transcription included, and dependent on the models: marked
"integration", and skipped anywhere the models are not installed.

    pytest -m integration
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.name_voice import voices_to_name
from greffier.application.process import Chain
from greffier.application.process import _as_stored_meeting as depuis_resultat
from tests.integration.prerequisites import (
    transcription_is_out_of_reach,
    voices_are_out_of_reach,
)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def config() -> Config:
    configuration = Config()
    hors_de_portee = transcription_is_out_of_reach(configuration)
    if hors_de_portee:
        pytest.skip(hors_de_portee)
    return configuration


def _fabriquer_cas(name: str, tmp_path_factory) -> Path:
    from make_hard_cases import CAS
    from make_meeting import make

    hors_de_portee = voices_are_out_of_reach(len(set(CAS[name][0].values())))
    if hors_de_portee:
        pytest.skip(hors_de_portee)
    voice, dialogue = CAS[name]
    destination = tmp_path_factory.mktemp("audio") / f"cas-{name}.wav"
    return make(destination, voice=voice, dialogue=dialogue)


def _process(config: Config, audio: Path):
    from greffier.wiring import wire_up

    config.minutes.engine = "aucun"
    chain: Chain = wire_up(config)
    chain.writer = None
    return chain.run_chain(audio, send=False)


@pytest.fixture(scope="session")
def resultat_trois_voix(config: Config, tmp_path_factory):
    """Three speakers, two of them close in timbre.

    The segmentation must neither join two of them by accident nor over-cut one
    person into several voices.
    """
    audio = _fabriquer_cas("trois-voix", tmp_path_factory)
    return _process(config, audio)


class TestTroisVoix:
    def test_the_three_voices_are_told_apart(self, resultat_trois_voix):
        """Three distinct voices, each with several seconds of material: not two, which
        would be a wrong join, and not more, which would be over-cutting left over.
        """
        temps = resultat_trois_voix.speaking_time()
        assert len(temps) == 3
        assert all(duration >= 5.0 for duration in temps.values())

    def test_both_self_introductions_are_found(self, resultat_trois_voix):
        """Jacques and Amélie introduce themselves; the third voice stays unnamed rather
        than inheriting somebody else's. A "merci Amélie" said just after the third
        person's turn is a deliberate trap in the fixture
        (`tools/make_hard_cases.py`), never to be asserted without more material.
        """
        assert set(resultat_trois_voix.names.values()) == {"Jacques", "Amélie"}
        assert len(resultat_trois_voix.names) == 2


@pytest.fixture(scope="session")
def resultat_proposition_breve(config: Config, tmp_path_factory):
    """C speaks once, briefly, and is never named by themselves: only a reference back
    just after their turn points at them, a clue too weak to be asserted, but one
    that must not be lost for all that.
    """
    audio = _fabriquer_cas("proposition-breve", tmp_path_factory)
    return _process(config, audio)


class TestPropositionBreve:
    def test_the_guess_is_there_in_the_outcome(self, resultat_proposition_breve):
        """The information is never lost: the reference back does produce a guess, never
        a certainty, since one clue is not enough.
        """
        temps = resultat_proposition_breve.speaking_time()
        voix_breve = min(temps, key=lambda v: temps[v])
        assert temps[voix_breve] < 10.0
        assert resultat_proposition_breve.propositions.get(voix_breve) is not None
        assert voix_breve not in resultat_proposition_breve.names

    def test_the_guess_survives_to_the_naming_screen(self, resultat_proposition_breve):
        """The defect fixed: the voices offered for naming must no longer silence a short
        voice that carries a guess.
        """
        meeting = depuis_resultat(resultat_proposition_breve, duration=60.0)
        voix_breve = min(
            resultat_proposition_breve.speaking_time(),
            key=lambda v: resultat_proposition_breve.speaking_time()[v],
        )
        input = next(v for v in voices_to_name(meeting) if v.voice == voix_breve)
        assert input.proposition is not None
