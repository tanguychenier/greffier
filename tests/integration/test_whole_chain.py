"""La chaîne réelle, de bout en bout, sur un vrai fichier audio.

Les tests unitaires vérifient les règles ; celui-ci vérifie qu'elles tiennent
face aux modèles. C'est lui qui a trouvé le défaut que les doublures ne
pouvaient pas voir : whisper fait commencer sa première réplique à 00:00,00
alors que la segmentation ne détecte la parole qu'à 00:00,30, si bien qu'une
auto-présentation tombait entre deux tours de parole et ne désignait personne.

L'audio est **synthétisé** : une vraie réunion contient des échanges de travail
et des voix identifiables, elle ne peut pas servir de jeu d'essai. Deux voix du
système suffisent à produire un fichier réel, passé par exactement le même
chemin que n'importe quel enregistrement.

Lent (transcription comprise) et dépendant des modèles : marqué « integration »,
et ignoré partout où les modèles ne sont pas installés.

    pytest -m integration
"""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.process import Chain

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration


def models_present(config: Config) -> bool:
    diarisation = config.paths.models / "diarisation"
    return (
        (config.paths.models / "ggml-large-v3-turbo.bin").exists()
        and (diarisation / "nemo_en_titanet_large.onnx").exists()
        and (diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").exists()
    )


@pytest.fixture(scope="session")
def config() -> Config:
    configuration = Config()
    if not models_present(configuration):
        pytest.skip("modèles absents — lance tools/install.py")
    if not shutil.which("whisper-cli"):
        pytest.skip("whisper.cpp absent")
    return configuration


@pytest.fixture(scope="session")
def meeting(tmp_path_factory) -> Path:
    """Fabrique une fois la fausse réunion, réutilisée par tous les tests."""
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    from make_meeting import make

    return make(tmp_path_factory.mktemp("audio") / "reunion.wav")


@pytest.fixture(scope="session")
def outcome(config: Config, meeting: Path):
    """Passe la fausse réunion dans la vraie chaîne, sans rédaction.

    Le rédacteur est débranché : appeler Claude ou Ollama depuis un test le
    rendrait lent, coûteux et dépendant du réseau. Ce que ce test doit prouver,
    c'est que l'audio arrive jusqu'à une transcription attribuée.
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
        """Le cœur du besoin : « Jacques » et « Sandy », pas « Personne 1 ».

        Chaque prénom est prononcé deux fois, de deux façons différentes — le
        cumul d'indices doit suffire à trancher sans demander à l'utilisateur.
        """
        assert set(outcome.names.values()) == {"Jacques", "Sandy"}

    def test_each_first_name_goes_to_a_different_voice(self, outcome):
        assert len(set(outcome.names)) == 2

    def test_introducing_oneself_wins_over_the_rest(self, outcome):
        """Celui qui dit « moi c'est Jacques » est Jacques, quoi qu'il arrive."""
        premiere = outcome.utterances[0]
        assert outcome.name_of(premiere.voice) == "Jacques"

    def test_a_mono_recording_raises_no_false_alarm(self, outcome):
        """Un fichier à un seul canal n'a pas de second canal manquant.

        L'alerte « aucun son système capté » n'a de sens que sur un
        enregistrement à deux canaux, où l'un des deux est effectivement vide.
        La déclencher sur du mono reviendrait à crier au loup à chaque
        enregistrement fait au simple micro.
        """
        assert outcome.warnings == []

    def test_the_rendered_transcription_is_attributed_and_timestamped(self, outcome):
        from greffier.application.render import render_transcript

        text = render_transcript(outcome)
        assert "[Jacques]" in text and "[Sandy]" in text
        assert "00:0" in text
        assert "Personne" not in text, "aucune voix ne devrait rester anonyme"


@pytest.mark.integration
class TestFromTheConversationToTheMinutes:
    """De bout en bout : ce qu'on écrit dans le chat parvient au rédacteur.

    Les tests unitaires vérifient chaque maillon. Celui-ci vérifie le fil :
    un message écrit dans la conversation d'une réunion, sur le disque, dans le
    format réel, et retrouvé dans ce que le rédacteur reçoit. C'est le chemin
    exact qui était rompu le 2026-09-10.
    """

    def test_a_message_typed_in_the_chat_reaches_the_writer(self, tmp_path):
        from greffier.adapters import conversations_file
        from greffier.adapters.configuration import Config
        from greffier.application.render import instructions_header
        from greffier.wiring import _instructions_of

        identifier = "2026-09-10_10h10_reunion"
        config = Config(paths={"donnees": tmp_path})
        fichier = conversations_file.file_for(config.paths.conversations, identifier)

        # Tel que la fenêtre l'écrit : une note de l'outil, une question de
        # l'assistant, puis la consigne humaine.
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
