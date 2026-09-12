"""The composition root: what is plugged where, according to the settings.

It holds no rule, which is exactly why it is worth testing: every mistake here
is silent. A writer wired where an assistant was meant leaves minutes that
answer questions; a transcriber built for the wrong engine fails an hour into a
meeting, on a machine where nothing else went wrong.
"""

from __future__ import annotations

import pytest

from greffier import wiring
from greffier.adapters.configuration import Config


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for cle in [c for c in __import__("os").environ if c.startswith("GREFFIER_")]:
        monkeypatch.delenv(cle)
    config = Config()
    config.paths.data = tmp_path / "donnees"
    config.paths.models = tmp_path / "modeles"
    # The models are checked for on construction, and rightly so: a chain built
    # without them would fail an hour into a meeting rather than before it.
    # Empty files are enough here -- nothing is loaded, only wired.
    diarisation = config.paths.models / "diarisation"
    (diarisation / "sherpa-onnx-pyannote-segmentation-3-0").mkdir(parents=True)
    (diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").touch()
    (diarisation / "nemo_en_titanet_large.onnx").touch()
    (config.paths.models / "ggml-large-v3-turbo.bin").touch()
    (config.paths.models / "ggml-silero-v5.1.2.bin").touch()
    return config


class TestWhoTranscribes:
    def test_whisper_cpp_is_given_its_two_models(self, config):
        config.transcription.engine = "whisper.cpp"
        transcripteur = wiring._transcriber(config)
        assert transcripteur.model.name == "ggml-large-v3-turbo.bin"
        assert transcripteur.vad.name == "ggml-silero-v5.1.2.bin"

    def test_elsewhere_faster_whisper_carries_the_model_name(self, config):
        config.transcription.engine = "faster-whisper"
        config.transcription.model = "large-v3"
        assert wiring._transcriber(config).taille == "large-v3"

    def test_the_live_one_follows_the_setting_when_there_is_one(self, config):
        """The live thread wants fast rather than precise: it is a choice."""
        config.transcription.engine = "faster-whisper"
        config.live.model = "small"
        assert wiring.light_transcriber(config).taille == "small"

    def test_with_no_whisper_cpp_model_the_live_one_gives_up(self, config):
        """Nothing to transcribe with, and saying so beats guessing."""
        config.transcription.engine = "whisper.cpp"
        for modele in config.paths.models.glob("ggml-*.bin"):
            modele.unlink()
        assert wiring.light_transcriber(config) is None


class TestWhoWritesTheMinutes:
    def test_ollama_keeps_everything_on_the_machine(self, config):
        config.minutes.engine = "ollama"
        assert type(wiring.writer(config)).__name__ == "OllamaWriter"

    def test_claude_carries_the_timeout_and_the_language(self, config):
        config.minutes.engine = "claude"
        config.minutes.timeout = 600
        config.minutes.language = "fr"
        redacteur = wiring.writer(config)
        assert redacteur.timeout == 600 and redacteur.language == "fr"

    def test_no_writer_at_all_is_a_setting(self, config):
        """« aucun »: transcribe, name the voices, and stop there."""
        config.minutes.engine = "aucun"
        assert wiring.writer(config) is None


class TestWhoAnswersInTheMeeting:
    def test_the_assistant_is_not_the_writer(self, config):
        """Its instructions are its own: it answers, it does not write minutes."""
        config.minutes.engine = "claude"
        assert wiring.assistant(config).consignes_propres
        assert not (wiring.writer(config).consignes_propres)

    def test_the_web_tools_follow_the_setting(self, config):
        config.minutes.engine = "claude"
        config.conversation.recherche_web = True
        assert wiring.assistant(config).tools
        config.conversation.recherche_web = False
        assert wiring.assistant(config).tools == ()

    def test_an_engine_that_cannot_converse_answers_nothing(self, config):
        config.minutes.engine = "aucun"
        assert wiring.assistant(config) is None


class TestWhatEarlierMeetingsLeft:
    def test_nothing_filed_yet_recalls_nothing(self, config):
        assert wiring.what_earlier_meetings_left(config) == ""

    def test_what_was_filed_comes_back(self, config):
        from greffier.domain.memory import Trace

        memoire = wiring.memory(config)
        memoire.remember(Trace(identifier="r1", title="recette",
                               decisions=("Jeudi.",)))
        assert "recette" in wiring.what_earlier_meetings_left(config)
        assert [t.title for t in memoire.recall()] == ["recette"]


@pytest.fixture
def sans_charger_les_modeles(monkeypatch):
    """The extractor really loads its network; wiring is not the place to.

    An empty file is enough to prove a path is passed along, and onnxruntime
    refuses it on load. What is measured here is what is plugged where.
    """
    class Doublure:
        def __init__(self, model, **_):
            self.model = model

    # Patched where it is used, not where it is defined: wiring binds the name
    # at import, and a patch on the adapter would never be seen.
    monkeypatch.setattr(wiring, "TitaNetExtractor", Doublure)


@pytest.mark.usefixtures("sans_charger_les_modeles")
class TestTheWholeChain:
    def test_it_stands_up_from_the_settings_alone(self, config):
        """The chain is built before a meeting, not during it."""
        config.minutes.engine = "aucun"
        config.transcription.engine = "faster-whisper"
        chaine = wiring.wire_up(config)
        assert chaine.transcriber is not None
        assert chaine.diariser is not None
        assert chaine.writer is None
        assert chaine.memory is not None

    def test_the_context_reaches_it(self, config):
        """The glossary is dictated to the writer, and it is wired here."""
        config.transcription.vocabulary = ["Jira", "recette"]
        config.minutes.engine = "aucun"
        assert "Jira" in wiring.wire_up(config).context_header

    def test_the_words_never_to_take_for_names_reach_it(self, config):
        config.speakers.not_first_names = ["Copernic"]
        config.minutes.engine = "aucun"
        # Lowercased on the way: the comparison is made against a transcription,
        # where the same word arrives capitalised or not.
        assert "copernic" in wiring.wire_up(config).not_first_names


class TestHowTheMinutesLeave:
    def test_no_recipient_means_no_sender_at_all(self, config):
        """Nobody to write to: the chain stops at the minutes on disk."""
        config.minutes.recipient = ""
        assert wiring._sender(config) is None

    def test_an_smtp_server_wins_over_everything(self, config):
        config.minutes.recipient = "equipe@exemple.fr"
        config.email.server = "smtp.exemple.fr"
        config.email.port = 587
        envoi = wiring._sender(config)
        assert type(envoi).__name__ == "SmtpSender"
        assert envoi.port == 587

    def test_with_no_server_the_minutes_land_in_a_folder(self, config, monkeypatch):
        """Linux and Windows: a folder is an honest way of not sending."""
        monkeypatch.setattr(wiring.platform, "system", lambda: "Linux")
        config.minutes.recipient = "equipe@exemple.fr"
        config.email.server = ""
        assert type(wiring._sender(config)).__name__ == "FileSender"

    def test_on_macos_outlook_is_tried_first(self, config, monkeypatch):
        monkeypatch.setattr(wiring.platform, "system", lambda: "Darwin")
        config.minutes.recipient = "equipe@exemple.fr"
        config.email.server = ""
        assert type(wiring._sender(config)).__name__ == "OutlookSender"

    def test_a_regeneration_needs_no_recipient(self, config):
        """Rewriting minutes is not sending them."""
        config.minutes.recipient = ""
        config.email.server = "smtp.exemple.fr"
        assert wiring._sender(config, exiger_destinataire=False) is not None


class TestTheRecording:
    def test_it_knows_where_the_audio_and_the_state_go(self, config):
        enregistrement = wiring.recording(config)
        assert enregistrement.dossier_audio == config.paths.recordings
        assert enregistrement.fichier_etat.name == "etat.json"

    def test_the_microphone_and_the_ceiling_come_from_the_settings(self, config):
        """Four hours by default: a meeting that never stopped filled a disk."""
        config.audio.input = "Jabra"
        config.audio.maximum_length = 7200
        capture = wiring._audio_recorder(config)
        assert capture.peripherique == "Jabra" and capture.maximum_length == 7200


class TestAMeetingPreparedBeforehand:
    def test_the_chain_opens_on_what_was_gathered(self, config,
                                                  sans_charger_les_modeles):
        from greffier.adapters import preparations_file

        config.minutes.engine = "aucun"
        preparation = preparations_file.open_one(config.paths.preparations, "recette")
        preparations_file.write(
            config.paths.preparations,
            preparation.raising("valider les anomalies").expecting("Jacques"),
        )
        chaine = wiring.wire_up(config)
        assert "valider les anomalies" in chaine.context_header
        assert chaine.expected_people == ("Jacques",)

    def test_a_meeting_prepared_by_nobody_opens_on_nothing(
            self, config, sans_charger_les_modeles):
        config.minutes.engine = "aucun"
        chaine = wiring.wire_up(config)
        assert "Préparation" not in chaine.context_header
        assert chaine.expected_people == ()

    def test_taking_it_leaves_none_for_the_next_meeting(self, config):
        """Consumed once: two meetings would each believe it was theirs."""
        from greffier.adapters import preparations_file

        preparation = preparations_file.open_one(config.paths.preparations, "recette")
        preparations_file.write(
            config.paths.preparations, preparation.raising("un point"))
        assert wiring.waiting_preparation(config) is not None
        wiring.take_the_preparation(config, "2026-09-12_reunion")
        assert wiring.waiting_preparation(config) is None

    def test_taking_when_there_is_nothing_is_not_an_error(self, config):
        wiring.take_the_preparation(config, "2026-09-12_reunion")


class TestTheContextIsBlended:
    def test_the_vocabulary_of_the_settings_is_in_it(self, config):
        config.transcription.vocabulary = ["Kanban"]
        assert "Kanban" in wiring.context(config).header()

    def test_an_empty_setting_gives_an_empty_header(self, config):
        assert wiring.context(config).header() == ""


class TestQuiOuvreLaCarteEnPremier:
    """Deux ONNX Runtime ne tiennent pas dans un processus.

    faster-whisper amène le sien avec son détecteur de voix, et celui qui ouvre
    en second lit un graphe corrompu ou tue l'interpréteur. Le découpage en
    tours de parole doit donc ouvrir le sien avant, sans quoi il se replie sur
    le processeur : 43 s au lieu de 5,8 s pour 40 s de réunion.
    """

    @pytest.fixture
    def places_gardees(self, monkeypatch):
        from greffier.adapters import cuda

        gardees = []
        monkeypatch.setattr(cuda, "keep_the_place", gardees.append)
        return gardees

    def test_the_place_is_kept_before_the_transcriber_is_built(self, config, places_gardees):
        config.transcription.engine = "faster-whisper"
        wiring._transcriber(config)
        assert [p.name for p in places_gardees] == ["nemo_en_titanet_large.onnx"]

    def test_the_live_transcriber_keeps_it_too(self, config, places_gardees):
        """Le direct tourne dans son propre processus, qui a la même règle."""
        config.transcription.engine = "faster-whisper"
        config.live.model = "small"
        wiring.light_transcriber(config)
        assert [p.name for p in places_gardees] == ["nemo_en_titanet_large.onnx"]

    def test_whisper_cpp_keeps_it_as_well(self, config, places_gardees):
        """whisper.cpp n'amène pas de rival, mais le chemin est le même."""
        config.transcription.engine = "whisper.cpp"
        wiring._transcriber(config)
        assert len(places_gardees) == 1
