"""A meeting held round a table, end to end.

The case had never been covered: everything used until then was a video call,
where the channel identifies with certainty whoever is recording. Round a
table, **everybody speaks into the same mic**: where the sound comes from names
nobody, and all that is left is the segmentation and the voice bank.

The audio is synthesised, three of the system's voices and a made-up dialogue,
and assembled in stereo the way the recording device returns it: the mic on
channel 0, the system loopback on channel 1 with the leak measured on the real
table meeting, -53 dB instead of the silence expected. It is that leak which
trapped the verdict, when a non-zero loopback was enough to conclude "video
call".

What this test does **not** measure: the quality of the transcription. The
synthetic voices return approximate text, measured, the same line gives
"L.S. Dominé, Depuis, I.S.W.A." from one voice to another, and a test
comparing them would measure `say`, not Greffier. It therefore checks what does
not depend on the timbre: the channel verdict, the number of voices, and the
refusal to decide.

    pytest -m integration
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.process import Chain
from greffier.domain.channels import LOCAL_VOICE
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


@pytest.fixture(scope="session")
def table(tmp_path_factory) -> Path:
    # Trois personnes autour de la table, donc trois timbres.
    hors_de_portee = voices_are_out_of_reach(3)
    if hors_de_portee:
        pytest.skip(hors_de_portee)
    from make_meeting import make_in_the_room

    return make_in_the_room(tmp_path_factory.mktemp("audio") / "table.wav")


@pytest.fixture(scope="session")
def outcome(config: Config, table: Path):
    from greffier.wiring import wire_up

    config.minutes.engine = "aucun"
    chain: Chain = wire_up(config)
    chain.writer = None
    return chain.run_chain(table, send=False)


class TestVerdictDeCanal:
    def test_the_leak_into_the_loopback_does_not_conclude_a_call(self, table: Path):
        import soundfile as sf

        from greffier.adapters.channels_file import levels_per_frame
        from greffier.domain.channels import over_video

        data, frequency = sf.read(table, dtype="float32", always_2d=True)
        assert data.shape[1] == 2, "le fichier d'essai doit être stéréo"
        mic = levels_per_frame(data[:, 0], frequency)
        boucle = levels_per_frame(data[:, 1], frequency)
        assert max(boucle) < -45.0, "la fuite doit rester sous le plancher de bruit"
        assert not over_video(mic, boucle)

    def test_the_mic_is_the_reference_for_both_channels(self, table: Path):
        """In a room the loopback has nothing to add: it is no longer used."""
        import numpy as np
        import soundfile as sf

        from greffier.adapters.channels_file import separer_canaux

        data, frequency = sf.read(table, dtype="float32", always_2d=True)
        channels = separer_canaux(data, frequency)
        assert channels.distante is False
        assert np.array_equal(channels.system, channels.mic)

    def test_no_passage_is_declared_local(self, table: Path):
        """The channel names nobody: better nothing than "Toi" wrongly.

        On a video call these passages are the one attribution that is never wrong.
        Round a table, keeping them would make every participant one and the same
        person, measured: three speakers reduced to one "moi" label.
        """
        from greffier.adapters.channels_file import FileChannelReader

        assert FileChannelReader().local_passages(table) == []


class TestChaineEnPresentiel:
    def test_the_meeting_is_transcribed(self, outcome):
        assert outcome.words > 60, "la transcription a perdu l'essentiel du dialogue"

    def test_nobody_is_labelled_as_the_local_voice(self, outcome):
        """The defect a meeting in a room could bring out, spelled out."""
        assert LOCAL_VOICE not in outcome.speaking_time()

    def test_the_participants_are_not_melted_into_one_voice(self, outcome):
        """Three people round a table stay several voices.

        The exact count depends on the timbre of the synthetic voices, two of which
        resemble each other enough to be stitched, so what is checked is that there is
        neither one single voice nor one participant per utterance.
        """
        significatives = outcome.significant_voices()
        assert 2 <= len(significatives) <= len(outcome.utterances)

    def test_fragments_do_not_count_as_participants(self, outcome):
        assert all(duration >= 10 for duration in outcome.significant_voices().values())

    def test_introducing_oneself_stays_right_without_the_channel_s_help(self, outcome):
        """"moi c'est Jacques" names whoever is speaking, channel or no channel."""
        assert outcome.name_of(outcome.utterances[0].voice) == "Jacques"

    def test_no_sentence_astride_is_attributed(self, outcome):
        """Une phrase que deux voix se partagent ne doit désigner personne.

        C'est la règle de `domain/attribution.py`, éprouvée ici sur la vraie
        chaîne : rien ne garantit que la découpe de whisper tombe sur un
        changement de locuteur, et le présentiel n'a pas le canal pour rattraper.
        """
        from greffier.domain.attribution import PART_MINIMALE, time_per_voice

        for utterance in outcome.utterances:
            cumuls = time_per_voice(utterance.span, outcome.turns)
            if not cumuls:
                continue
            part = max(cumuls.values()) / sum(cumuls.values())
            if part < PART_MINIMALE:
                assert utterance.voice is None, (
                    f"« {utterance.text[:40]} » est partagée à {part:.0%} "
                    "et se voit pourtant attribuer une voix"
                )
