"""The voice bank, from one meeting to the next: the heart of the need.

Two meetings synthesised with the same voices. First names are said in the
first, none in the second. If the second names the participants anyway, it can
only be by recognising their voices: that is the whole promise of the tool, and
it is checked here end to end.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.adapters.store_files import FileStore
from greffier.adapters.voice_bank_files import FileVoiceBank
from greffier.application.name_voice import Naming, voices_to_name
from greffier.application.process import _as_stored_meeting as depuis_resultat
from tests.integration.prerequisites import (
    transcription_is_out_of_reach,
    voices_are_out_of_reach,
)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def atelier(tmp_path_factory):
    """A clean machine: an empty bank, no meeting known."""
    config = Config()
    for hors_de_portee in (voices_are_out_of_reach(2), transcription_is_out_of_reach(config)):
        if hors_de_portee:
            pytest.skip(hors_de_portee)

    root = tmp_path_factory.mktemp("poste")
    config.paths.data = root
    config.minutes.engine = "aucun"

    from make_meeting import DIALOGUE_WITHOUT_NAMES, make

    premiere = make(root / "reunion-1.wav")
    seconde = make(root / "reunion-2.wav", dialogue=DIALOGUE_WITHOUT_NAMES)
    return config, premiere, seconde


def process(config, audio):
    from greffier.wiring import wire_up

    chain = wire_up(config)
    chain.writer = None
    outcome = chain.run_chain(audio, send=False)
    duration = outcome.turns[-1].span.end if outcome.turns else 0.0
    store = FileStore(config.paths.data / "reunions")
    store.record(depuis_resultat(outcome, duration))
    return outcome


class TestReconnaissanceEntreReunions:
    def test_le_parcours_complet(self, atelier):
        """Première réunion → nommage → seconde réunion reconnue toute seule."""
        from make_meeting import first_names

        config, premiere, seconde = atelier
        bank = FileVoiceBank(config.paths.voice_bank)
        store = FileStore(config.paths.data / "reunions")

        # 1. The first meeting: the first names come from what is said.
        outcome = process(config, premiere)
        assert set(outcome.names.values()) == set(first_names())

        # 2. The person confirms: they decide, and nothing enters the bank
        #    without that gesture.
        from greffier.adapters.voiceprints_titanet import TitaNetExtractor

        namer = Naming(
            store=store,
            bank=bank,
            extractor=TitaNetExtractor(
                config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
            ),
        )
        for voice, name in outcome.names.items():
            namer.name_voice(premiere.stem, voice, name)
        assert {p.name for p in bank.people()} == set(first_names())

        # 3. The second meeting says no first name at all.
        second_resultat = process(config, seconde)
        transcription = " ".join(r.text for r in second_resultat.utterances)
        assert not any(prenom in transcription for prenom in first_names())

        # 4. And yet both are named: that can only come from the voice.
        assert set(second_resultat.names.values()) == set(first_names())

    def test_the_bank_does_not_name_just_anyone(self, atelier, tmp_path):
        """A bank holding a stranger's voice must recognise nothing."""
        config, _, seconde = atelier
        from greffier.domain.voiceprints import normalise
        from greffier.wiring import wire_up

        etrangere = FileVoiceBank(tmp_path / "banque-etrangere")
        etrangere.record("Personne d'autre", normalise([1.0] + [0.0] * 191))

        chain = wire_up(config)
        chain.bank = etrangere
        chain.writer = None
        outcome = chain.run_chain(seconde, send=False)
        assert "Personne d'autre" not in outcome.names.values()

    def test_the_voices_to_name_come_with_an_extract(self, atelier):
        """Le parcours réel : écouter dix secondes, taper un nom."""
        config, premiere, _ = atelier
        meeting = FileStore(config.paths.data / "reunions").read(premiere.stem)
        candidates = voices_to_name(meeting)
        assert len(candidates) == 2
        assert all(c.extrait is not None and c.extrait.duration >= 3 for c in candidates)
        # From the most talkative down: the ones that matter most come first.
        assert candidates[0].duration >= candidates[1].duration


@pytest.mark.integration
class TestSplittingAfterTheMeetingEndToEnd:
    """The whole gesture: join, write, read back, split, write again.

    What was missing: the live thread knew how to go back, the after-meeting chain
    did not. Two people joined by mistake stayed that way to the minutes, and the
    minutes announced one participant too few.

    This test goes through the real file store, not a double: persistence was what
    was missing, and persistence is what has to be covered.
    """

    def _reunion(self, tmp_path):
        from datetime import UTC, datetime

        from greffier.domain.meeting import StoredMeeting
        from greffier.domain.models import Span, SpeakerTurn, Utterance

        return StoredMeeting(
            identifier="2026-09-10_10h10_reunion",
            audio=tmp_path / "r.wav",
            processed_at=datetime.now(UTC),
            duration=120.0,
            utterances=[
                Utterance(Span(0, 40), "on cale la recette jeudi", "v1"),
                Utterance(Span(50, 90), "le devis part demain matin", "v2"),
            ],
            turns=[SpeakerTurn(Span(0, 40), "v1"), SpeakerTurn(Span(50, 90), "v2")],
            names={"v1": "Tanguy", "v2": "Pascal"},
            propositions={},
            warnings=[],
        )

    def test_le_cycle_complet(self, tmp_path):
        from greffier.adapters.store_files import FileStore

        magasin = FileStore(tmp_path / "reunions")
        detail = self._reunion(tmp_path)
        detail.join_into("v2", "v1")
        magasin.record(detail)

        # What the minutes would have announced: one person only.
        relue = magasin.read("2026-09-10_10h10_reunion")
        assert list(relue.names.values()) == ["Tanguy"]
        assert {t.voice for t in relue.turns} == {"v1"}

        # The gesture that was missing, and it survives being written.
        assert relue.can_split("v1")
        relue.split("v1")
        magasin.record(relue)

        finale = magasin.read("2026-09-10_10h10_reunion")
        assert sorted(finale.names.values()) == ["Pascal", "Tanguy"]
        assert {t.voice for t in finale.turns} == {"v1", "v2"}
        assert {u.voice for u in finale.utterances} == {"v1", "v2"}
        assert not finale.can_split("v1"), "défaite une fois, pas deux"

    def test_the_speaking_time_goes_back_to_each_of_them(self, tmp_path):
        """It is what the minutes announce: who spoke for how long."""
        detail = self._reunion(tmp_path)
        detail.join_into("v2", "v1")
        assert detail.speaking_time()["v1"] == 80.0
        detail.split("v1")
        temps = detail.speaking_time()
        assert temps["v1"] == 40.0
        assert temps["v2"] == 40.0
