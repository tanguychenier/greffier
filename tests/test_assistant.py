"""L'assistant de première configuration, avec des réponses simulées."""

import json

from greffier.adapters import assistant_terminal as assistant
from greffier.adapters import system_diagnostic as diagnostic


class ScriptedDialogue:
    """Replays a conversation written in advance, and keeps what was said."""

    def __init__(self, answers=None, confirmations=None, choix=None):
        self.answers = list(answers or [])
        self.confirmations = list(confirmations or [])
        self.choix = list(choix or [])
        self.affiche = []

    def ask(self, question, defaut=""):
        return self.answers.pop(0) if self.answers else defaut

    def confirm(self, question, defaut=True):
        return self.confirmations.pop(0) if self.confirmations else defaut

    def show(self, text):
        self.affiche.append(text)

    def choose(self, question, options, defaut):
        return self.choix.pop(0) if self.choix else options[defaut][0]

    def dialogue(self):
        return assistant.Dialogue(
            ask=self.ask, confirm=self.confirm,
            show=self.show, choose=self.choose,
        )

    @property
    def everything_said(self):
        return "\n".join(self.affiche)


def recorder(memoire=16.0, disque=100.0, system="Darwin"):
    return diagnostic.Recorder(
        system=system, architecture="arm64", memory_gb=memoire,
        disque_libre_go=disque, speedup="metal",
    )


def state(constats=None, **infos):
    return diagnostic.Diagnostic(recorder=recorder(**infos), constats=constats or [])


class TestChoosingTheTranscriptionModel:
    def test_a_comfortable_machine_takes_the_large_model(self):
        assert recorder(memoire=36).advised_model == "large-v3-turbo"

    def test_a_modest_machine_takes_a_smaller_model(self):
        """Offering the biggest everywhere would bog the machine down in a meeting."""
        assert recorder(memoire=6).advised_model == "medium"
        assert recorder(memoire=2).advised_model == "small"

    def test_outside_macos_the_large_model_has_another_name(self):
        assert recorder(memoire=32, system="Linux").advised_model == "large-v3"

    def test_the_chosen_model_lands_in_the_settings(self):
        simule = ScriptedDialogue()
        answers = assistant.Answers()
        assistant.hardware_step(simule.dialogue(), state(memoire=4), answers)
        assert answers.values["GREFFIER_TRANSCRIPTION__MODEL"] == "medium"


class TestHowTheMinutesAreDelivered:
    def test_by_email_through_outlook_asks_for_no_password(self, monkeypatch):
        """The account is already signed in: nothing to store, and that is better."""
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(confirmations=[True], answers=["josiane@exemple.fr"])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == "josiane@exemple.fr"
        assert "GREFFIER_EMAIL__SERVER" not in answers.values
        assert any("Automatisation" in action for action in answers.to_do)

    def test_by_email_without_outlook_asks_for_the_server(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: False)
        simule = ScriptedDialogue(
            confirmations=[True],
            answers=["moi@exemple.fr", "smtp.exemple.fr", "587", "moi@exemple.fr"],
        )
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_EMAIL__SERVER"] == "smtp.exemple.fr"

    def test_the_password_is_never_written_down(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: False)
        simule = ScriptedDialogue(
            confirmations=[True],
            answers=["moi@exemple.fr", "smtp.exemple.fr", "587", "moi"],
        )
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert not any("MOT_DE_PASSE" in key for key in answers.values)
        assert "environnement" in simule.everything_said

    def test_with_no_email_a_folder_is_chosen(self, tmp_path):
        simule = ScriptedDialogue(confirmations=[False], answers=[str(tmp_path / "cr")])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_PATHS__DATA"] == str(tmp_path)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == ""


class TestWhoWritesTheMinutes:
    def test_a_missing_writer_is_offered_for_installation(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: False)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: False)
        simule = ScriptedDialogue(confirmations=[False], choix=["aucun"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert any("install" in action for action in answers.to_do)

    def test_a_writer_installed_but_not_signed_in_is_flagged(self, monkeypatch):
        """Without this check the failure would come after an hour of transcription, at
        the worst possible moment.
        """
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: False)
        simule = ScriptedDialogue(choix=["claude"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert "aucune session" in simule.everything_said
        assert any("claude" in action for action in answers.to_do)

    def test_a_ready_writer_is_chosen_by_default(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        simule = ScriptedDialogue()
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__ENGINE"] == "claude"

    def test_the_model_is_asked_for_and_defaults_to_opus(self, monkeypatch):
        """The second of the range, not the first: writing up from an already attributed
        transcription is summarising, and the top of the range returns the same
        document while eating a quota much faster.
        """
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        simule = ScriptedDialogue()
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__MODEL"] == "opus"
        assert assistant.MODELES_CLAUDE[0][0] == "opus", "le défaut est le premier proposé"

    def test_another_model_can_be_chosen(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        simule = ScriptedDialogue(choix=["claude", "haiku"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__MODEL"] == "haiku"

    def test_with_no_writer_no_model_is_written_down(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: False)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: False)
        simule = ScriptedDialogue(confirmations=[False], choix=["aucun"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert "GREFFIER_MINUTES__MODEL" not in answers.values

    def test_the_models_offered_are_aliases_the_tool_accepts(self):
        """`claude --model` expects an alias (fable, opus, sonnet) or a full name; a
        convenience label passed as it is would make the call fail.
        """
        for key, label_text in assistant.MODELES_CLAUDE:
            assert key == key.lower() and " " not in key
            assert label_text.lower().startswith(key)


class TestTheVocabularyAsked:
    def test_the_vocabulary_doubles_as_an_exclusion_list(self):
        """Sans cela, « merci Copernic » créerait un participant."""
        simule = ScriptedDialogue(answers=["Copernic, Kanban , Trello"])
        answers = assistant.Answers()
        assistant.vocabulary_step(simule.dialogue(), state(), answers)
        words = json.loads(answers.values["GREFFIER_TRANSCRIPTION__VOCABULARY"])
        assert words == ["Copernic", "Kanban", "Trello"]
        assert json.loads(answers.values["GREFFIER_SPEAKERS__NOT_FIRST_NAMES"]) == words

    def test_it_can_be_skipped(self):
        simule = ScriptedDialogue(answers=[""])
        answers = assistant.Answers()
        assistant.vocabulary_step(simule.dialogue(), state(), answers)
        assert "GREFFIER_TRANSCRIPTION__VOCABULARY" not in answers.values


class TestWritingTheSettingsFile:
    def test_the_file_produced_is_readable_by_the_settings(self, tmp_path, monkeypatch):
        """La boucle complète : l'assistant écrit, la configuration relit."""
        from greffier.adapters.configuration import Config

        answers = assistant.Answers()
        answers.place("GREFFIER_MINUTES__ENGINE", "ollama")
        answers.place("GREFFIER_MINUTES__RECIPIENT", "moi@exemple.fr")
        target = assistant.write(answers, tmp_path / ".env")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "vide"))
        config = Config()
        assert config.minutes.engine == "ollama"
        assert config.minutes.recipient == "moi@exemple.fr"
        assert target.exists()

    def test_existing_settings_are_kept(self, tmp_path):
        """Nobody's settings are destroyed without a trace."""
        target = tmp_path / ".env"
        target.write_text("GREFFIER_ANCIEN=1\n", encoding="utf-8")
        assistant.write(assistant.Answers(), target)
        assert (tmp_path / ".env.precedent").read_text().strip() == "GREFFIER_ANCIEN=1"


class TestTheWholeWalkthrough:
    def test_from_start_to_end_without_installing_anything(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(
            confirmations=[True],
            answers=["josiane@exemple.fr", "Copernic, OASIS"],
        )
        answers = assistant.run_chain(simule.dialogue(), state())
        assert answers.values["GREFFIER_MINUTES__ENGINE"] == "claude"
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == "josiane@exemple.fr"
        assert answers.values["GREFFIER_TRANSCRIPTION__ENGINE"] == "whisper.cpp"
        assert "Copernic" in answers.values["GREFFIER_SPEAKERS__NOT_FIRST_NAMES"]

    def test_a_blocking_gap_is_announced_before_anything_else(self):
        manque = diagnostic.Reading(
            name="ffmpeg", present=False, detail="absent",
            remede="brew install ffmpeg", bloquant=True,
        )
        simule = ScriptedDialogue(confirmations=[False], answers=[""])
        answers = assistant.run_chain(simule.dialogue(), state(constats=[manque]))
        assert "brew install ffmpeg" in answers.to_do


class TestTheEmailAddress:
    def test_an_invalid_address_is_asked_for_again(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(confirmations=[True], answers=["pas-une-adresse", "moi@ex.fr"])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == "moi@ex.fr"

    def test_with_no_address_it_does_not_claim_it_will_send(self, monkeypatch):
        """Saying "yes to email" then typing nothing produced settings that promised a
        sending and sent nothing.
        """
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(confirmations=[True], answers=["", "", ""])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == ""
        assert "restera simplement sur le disque" in simule.everything_said
