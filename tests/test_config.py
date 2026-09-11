"""La configuration : valeurs par défaut, .env, environnement, TOML."""

from pathlib import Path

import pytest

from greffier.adapters.configuration import Config


@pytest.fixture(autouse=True)
def without_an_environment(monkeypatch, tmp_path):
    """Isolates every test from the machine it runs on.

    Without it the developer's own settings, the ones living in
    ~/.config/greffier, are read by the TOML source and the tests pass or fail
    depending on the machine.
    """
    import os

    for key in list(os.environ):
        if key.startswith("GREFFIER_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)


class TestTheDefaults:
    def test_claude_writes_the_minutes_by_default(self):
        """A deliberate choice: writing up a set of minutes goes beyond what a laptop
        model can do. The one link that is not local, and it is owned.
        """
        assert Config().minutes.engine == "claude"

    def test_a_machine_with_no_settings_works(self):
        config = Config()
        assert config.transcription.language == "fr"
        assert config.audio.maximum_length == 14_400
        assert config.speakers.people is None

    def test_an_empty_vocabulary_produces_no_seed(self):
        assert Config().transcription.prompt_seed == ""

    def test_the_vocabulary_becomes_a_seed(self):
        config = Config(transcription={"vocabulaire": ["Jira", "recette"]})
        assert "Jira, recette" in config.transcription.prompt_seed


class TestWhichModelWritesTheMinutes:
    """Which model writes them, and why it is not the most powerful one."""

    def test_claude_takes_the_second_of_the_range_by_default(self):
        """Writing up from an already attributed transcription is summarising: the top of
        the range returns the same document while eating a quota much faster. The
        choice stays open, both ways.
        """
        assert Config().minutes.effective_model == "opus"

    def test_an_explicit_setting_wins(self):
        config = Config(minutes={"moteur": "claude", "modele": "fable"})
        assert config.minutes.effective_model == "fable"

    def test_ollama_has_its_own_default(self):
        """Un alias Claude Code n'a aucun sens pour Ollama, et l'inverse non plus."""
        assert Config(minutes={"moteur": "ollama"}).minutes.effective_model == "qwen3:8b"

    def test_with_no_writer_there_is_no_model(self):
        assert Config(minutes={"moteur": "aucun"}).minutes.effective_model == ""

    def test_the_model_can_be_set_from_the_environment(self):
        """To force it for one command, without touching the file."""
        import os

        os.environ["GREFFIER_MINUTES__MODEL"] = "sonnet"
        try:
            assert Config().minutes.effective_model == "sonnet"
        finally:
            del os.environ["GREFFIER_MINUTES__MODEL"]


class TestTheLanguage:
    """The language code, and what its absence means."""

    def test_french_by_default(self):
        """Announcing it beats making it guess when it is known."""
        assert Config().transcription.language == "fr"

    def test_empty_means_detect_it(self):
        """The same convention as an empty mic: the machine is left to decide."""
        assert Config(transcription={"langue": ""}).transcription.language == ""


class TestTheLookOfTheWindow:
    def test_the_theme_follows_the_system_by_default(self):
        """Une application qui impose son goût jure avec le reste de l'écran."""
        assert Config().appearance.theme == "systeme"

    def test_the_theme_can_be_forced(self):
        assert Config(appearance={"theme": "sombre"}).appearance.theme == "sombre"


class TestWhereTheSettingsComeFrom:
    def test_the_environment_comes_first(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_MINUTES__ENGINE", "ollama")
        assert Config().minutes.engine == "ollama"

    def test_an_env_file_is_read(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text(
            "GREFFIER_MINUTES__RECIPIENT=moi@exemple.fr\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        assert Config().minutes.recipient == "moi@exemple.fr"

    def test_the_environment_wins_over_the_env_file(self, tmp_path, monkeypatch):
        """On doit pouvoir forcer un réglage le temps d'une commande."""
        (tmp_path / ".env").write_text("GREFFIER_MINUTES__ENGINE=claude\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GREFFIER_MINUTES__ENGINE", "aucun")
        assert Config().minutes.engine == "aucun"

    def test_lists_are_given_as_json(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_SPEAKERS__NOT_FIRST_NAMES", '["Copernic","Trello"]')
        assert Config().speakers.not_first_names == ["Copernic", "Trello"]

    def test_an_explicit_toml_file_is_read(self, tmp_path):
        file = tmp_path / "config.toml"
        file.write_text(
            '[compte_rendu]\nmoteur = "ollama"\nmodele = "qwen3:8b"\n', encoding="utf-8"
        )
        config = Config.load(file)
        assert (config.minutes.engine, config.minutes.model) == ("ollama", "qwen3:8b")

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        """Cas d'un poste qui vient d'installer."""
        assert Config.load(tmp_path / "nulle-part.toml").minutes.engine == "claude"

    def test_an_unreadable_file_is_an_error(self, tmp_path):
        """Mieux vaut le dire qu'appliquer autre chose que ce qui est écrit."""
        file = tmp_path / "casse.toml"
        file.write_text("[compte_rendu\nmoteur =", encoding="utf-8")
        with pytest.raises(ValueError, match="illisible"):
            Config.load(file)


class TestWhereThingsLive:
    def test_the_subfolders_follow_from_the_data_folder(self, tmp_path):
        config = Config(paths={"donnees": tmp_path})
        assert config.paths.recordings == tmp_path / "enregistrements"
        assert config.paths.voice_bank == tmp_path / "banque-de-voix"

    def test_the_data_path_is_a_setting(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_PATHS__DATA", "/ailleurs")
        assert Config().paths.data == Path("/ailleurs")


class TestTheAssistantIsOnByDefault:
    """It follows the meeting and answers: that is its job.

    The day the window stopped exposing this setting, keeping one button for the
    voice alone, nothing could switch it on any more. The assistant did not answer
    and nobody could know why. Found out during a meeting, which is the worst
    moment.
    """

    def test_it_is_on_with_nothing_set(self):
        from greffier.adapters.configuration import Config

        assert Config().assistant.active

    def test_but_it_does_not_speak_of_its_own_accord(self):
        """Répondre est sans risque ; parler de soi-même se décide."""
        from greffier.adapters.configuration import Config

        assistant = Config().assistant
        assert not assistant.initiative
        assert not assistant.demander_les_voix


class TestTheFirstNamesThatWereTested:
    """A list and not a free text field.

    A first name typed at random is not necessarily returned by the transcription
    model, and nothing would tell whoever typed it: they would be calling into the
    void. Each of these passed four trials, two turns of phrase and two synthetic
    voices, and five traps, sentences without the name.
    """

    def test_every_first_name_carries_a_voice(self):
        from greffier.adapters.configuration import FIRST_NAMES, KINDS

        assert FIRST_NAMES, "la liste est vide"
        assert all(speaker_index in KINDS for speaker_index in FIRST_NAMES.values())

    def test_both_genders_are_offered(self):
        """Sinon le choix n'en est pas un."""
        from greffier.adapters.configuration import FIRST_NAMES

        assert set(FIRST_NAMES.values()) == {0, 1}

    def test_the_first_name_sets_its_voice(self):
        from greffier.adapters.configuration import AssistantSettings

        assert AssistantSettings(name="Lucie").effective_speaker == 0
        assert AssistantSettings(name="Martin").effective_speaker == 1

    def test_a_name_outside_the_list_keeps_the_setting(self):
        """Le fichier de configuration autorise un prénom libre."""
        from greffier.adapters.configuration import AssistantSettings

        assert AssistantSettings(name="Aurélien", speaker_index=1).effective_speaker == 1

    def test_no_dropped_name_lingers_in_the_list(self):
        """« Élise » se déclenche sur « elle a lu ci et ça », mesuré.

        « Greffier » lui-même est écarté pour la même raison : « le greffe du
        tribunal » suffisait à l'appeler.
        """
        from greffier.adapters.configuration import FIRST_NAMES

        assert "Élise" not in FIRST_NAMES
        assert "Greffier" not in FIRST_NAMES

    def test_every_first_name_recognises_itself(self):
        """Le contrôle minimal : la règle d'appel doit le voir dans une phrase."""
        from greffier.adapters.configuration import FIRST_NAMES
        from greffier.domain.participation import called_by_name

        for first_name in FIRST_NAMES:
            assert called_by_name(f"{first_name}, tu peux noter ça ?", first_name), first_name

    def test_no_first_name_fires_on_an_ordinary_sentence(self):
        from greffier.adapters.configuration import FIRST_NAMES
        from greffier.domain.participation import called_by_name

        pieges = [
            "on passe au point suivant, la recette est terminée",
            "il faut qu'on parle du budget et des livraisons",
            "le sprint avance bien, la merge request est prête",
            "elle a lu ci et ça dans la documentation",
            "on a vu ça lundi avec l'équipe de Bordeaux",
        ]
        for first_name in FIRST_NAMES:
            for piege in pieges:
                assert not called_by_name(piege, first_name), f"{first_name} sur « {piege} »"


class TestTheKeysOfTheFileNeverMove:
    """The settings file on a machine has to stay readable.

    Every field carries a `validation_alias`: the name of the field in Python can
    move to English without the key in the file changing. An update that made a
    machine's `config.toml` unreadable would wipe its settings in silence, and
    there is no reason to put anybody through that.
    """

    #: Un fichier tel qu'un poste en porte aujourd'hui.
    EXISTANT = """
[audio]
micro = "Micro MacBook Pro"

[transcription]
moteur = "whisper.cpp"
modele = "large-v3"
vocabulaire = ["Jira", "recette"]

[compte_rendu]
moteur = "claude"
destinataire = "moi@exemple.fr"
delai = 1800

[assistant]
actif = true
nom = "Lucie"
voix = "kokoro"
initiative = false

[apparence]
theme = "sombre"
"""

    def _config_in(self, tmp_path):
        from greffier.adapters.configuration import Config

        file = tmp_path / "config.toml"
        file.write_text(self.EXISTANT, encoding="utf-8")
        return Config.load(file)

    def test_every_section_is_read_back(self, tmp_path):
        config = self._config_in(tmp_path)
        assert config.audio.mic == "Micro MacBook Pro"
        assert config.transcription.model == "large-v3"
        assert config.transcription.vocabulary == ["Jira", "recette"]
        assert config.minutes.recipient == "moi@exemple.fr"
        assert config.minutes.timeout == 1800
        assert config.assistant.name == "Lucie"
        assert config.assistant.voice == "kokoro"
        assert config.assistant.active is True
        assert config.assistant.initiative is False
        assert config.appearance.theme == "sombre"

    def test_the_keys_written_back_are_the_same(self, tmp_path):
        """Ce qui est réécrit doit pouvoir être relu : c'est le vrai cycle."""
        from greffier.adapters.configuration import Config, render

        rendered = render(self._config_in(tmp_path))
        deuxieme = tmp_path / "encore.toml"
        deuxieme.write_text(rendered, encoding="utf-8")
        relu = Config.load(deuxieme)
        assert relu.assistant.name == "Lucie"
        assert relu.minutes.recipient == "moi@exemple.fr"
        assert relu.appearance.theme == "sombre"

    def test_an_unknown_key_does_not_bring_it_down(self, tmp_path):
        """Un réglage retiré d'une version à l'autre ne doit rien casser."""
        from greffier.adapters.configuration import Config

        file = tmp_path / "config.toml"
        file.write_text('[assistant]\nnom = "Alice"\nreglage_disparu = 3\n',
                           encoding="utf-8")
        assert Config.load(file).assistant.name == "Alice"
