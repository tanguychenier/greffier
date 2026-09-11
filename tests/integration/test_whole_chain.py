"""The real chain, end to end, on a real audio file.

The unit tests check the rules; this one checks that they hold in front of the
models. It is the one that found the defect no double could see: whisper starts
its first utterance at 00:00.00 while the segmentation only detects speech at
00:00.30, so a self-introduction fell between two speaking turns and named
nobody.

The audio is **synthesised**: a real meeting holds work discussions and
recognisable voices, and cannot serve as a test fixture. Two of the system's
voices are enough to produce a real file, put through exactly the same path as
any other recording.

Slow, transcription included, and dependent on the models: marked
"integration", and skipped anywhere the models are not installed.

    pytest -m integration
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.process import Chain
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
def meeting(tmp_path_factory) -> Path:
    """Builds the fake meeting once, reused by every test."""
    hors_de_portee = voices_are_out_of_reach(2)
    if hors_de_portee:
        pytest.skip(hors_de_portee)
    from make_meeting import make

    return make(tmp_path_factory.mktemp("audio") / "reunion.wav")


@pytest.fixture(scope="session")
def outcome(config: Config, meeting: Path):
    """Puts the fake meeting through the real chain, with no write-up.

    The writer is unplugged: calling Claude or Ollama from a test would make it
    slow, costly and dependent on the network. What this test has to prove is that
    the audio reaches an attributed transcription.
    """
    from greffier.wiring import wire_up

    config.minutes.engine = "aucun"
    chain: Chain = wire_up(config)
    chain.writer = None
    return chain.run_chain(meeting, send=False)


class TestChaineReelle:
    def test_l_audio_synthetise_est_bien_transcrit(self, outcome):
        assert outcome.words > 60, "la transcription a perdu l'essentiel du dialogue"

    def test_the_two_voices_are_told_apart(self, outcome):
        """Cinq répliques alternées, deux voix : ni fusion, ni sur-découpage."""
        assert len(outcome.significant_voices()) == 2

    def test_fragments_do_not_count_as_participants(self, outcome):
        significatives = outcome.significant_voices()
        assert all(duration >= 10 for duration in significatives.values())

    def test_both_first_names_are_found(self, outcome):
        """The heart of the need: "Jacques" and "Sandy", not "Personne 1".

        Each first name is said twice, in two different ways: the clues adding up must
        be enough to decide without asking anybody.
        """
        from make_meeting import first_names

        assert set(outcome.names.values()) == set(first_names())

    def test_each_first_name_goes_to_a_different_voice(self, outcome):
        assert len(set(outcome.names)) == 2

    def test_introducing_oneself_wins_over_the_rest(self, outcome):
        """Whoever says "moi c'est Jacques" is Jacques, whatever else happens."""
        premiere = outcome.utterances[0]
        assert outcome.name_of(premiere.voice) == "Jacques"

    def test_a_mono_recording_raises_no_false_alarm(self, outcome):
        """A single-channel file has no missing second channel.

        The "no system sound captured" warning only means something on a two-channel
        recording, where one of the two really is empty. Raising it on mono would be
        crying wolf on every recording made with a plain mic.
        """
        assert outcome.warnings == []

    def test_the_rendered_transcription_is_attributed_and_timestamped(self, outcome):
        from greffier.application.render import render_transcript

        text = render_transcript(outcome)
        from make_meeting import first_names

        assert all(f"[{prenom}]" in text for prenom in first_names())
        assert "00:0" in text
        assert "Personne" not in text, "aucune voix ne devrait rester anonyme"


@pytest.mark.integration
class TestFromTheConversationToTheMinutes:
    """End to end: what is typed in the chat reaches the writer.

    The unit tests cover each link. This one covers the thread: a message typed
    into a meeting's conversation, on disk, in the real format, and found again in
    what the writer receives. It is the exact path that was broken on 2026-09-10.
    """

    def test_a_message_typed_in_the_chat_reaches_the_writer(self, tmp_path):
        from greffier.adapters import conversations_file
        from greffier.adapters.configuration import Config
        from greffier.application.render import instructions_header
        from greffier.wiring import _instructions_of

        identifier = "2026-09-10_10h10_reunion"
        config = Config(paths={"donnees": tmp_path})
        fichier = conversations_file.file_for(config.paths.conversations, identifier)

        # As the window writes it: a note from the tool, a question from the
        # assistant, then the instruction from the person.
        conversations_file.add(fichier, "note", "❓ J'ai entendu « ailleurs ».")
        conversations_file.add(fichier, "lucie", "Qui prend la migration ?")
        conversations_file.add(fichier, "moi", "Il n'y a pas de sophie dans la réunion")
        conversations_file.add(fichier, "greffier", "Le compte rendu est prêt.")

        consignes = _instructions_of(config)(identifier)
        assert consignes == ["Il n'y a pas de sophie dans la réunion"], consignes

        entete = instructions_header(consignes)
        assert "Il n'y a pas de sophie" in entete
        assert "ailleurs" not in entete, "une note n'est pas une consigne"
        assert "migration" not in entete, "une question de l'assistant non plus"

    def test_the_order_of_the_instructions_is_the_meeting_s(self, tmp_path):
        """Une consigne plus tardive corrige une plus ancienne."""
        from greffier.adapters import conversations_file
        from greffier.adapters.configuration import Config
        from greffier.wiring import _instructions_of

        identifier = "2026-09-10_13h08_reunion"
        config = Config(paths={"donnees": tmp_path})
        fichier = conversations_file.file_for(config.paths.conversations, identifier)
        for texte in ("c'est Florent qui a dit ça", "non, c'était Pascal"):
            conversations_file.add(fichier, "moi", texte)
        assert _instructions_of(config)(identifier) == [
            "c'est Florent qui a dit ça", "non, c'était Pascal",
        ]

    def test_no_instruction_when_nobody_said_anything(self, tmp_path):
        from greffier.adapters.configuration import Config
        from greffier.wiring import _instructions_of

        config = Config(paths={"donnees": tmp_path})
        assert _instructions_of(config)("2026-01-01_09h00_reunion") == []
