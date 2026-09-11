"""Writing `config.toml`: what is set from the window has to read back.

The risk is not writing a line badly, it is losing one. The file is regenerated
on every save: a field the module forgot disappears from the machine, silently,
and the next transcription is the worse for it with nothing to announce it.
These tests therefore mostly cover the **fidelity of the round trip**, section
by section.
"""

import tomllib

import pytest

from greffier.adapters import configuration as settings
from greffier.adapters.configuration import Config


@pytest.fixture(autouse=True)
def without_an_environment(monkeypatch, tmp_path):
    """Isolates from the machine: otherwise the personal settings are read back."""
    import os

    for key in list(os.environ):
        if key.startswith("GREFFIER_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def filled_in():
    """Settings where every section carries something other than the default."""
    return Config(
        audio={"micro": "Jabra EVOLVE 30 II", "duree_maximale": 7200},
        transcription={"modele": "large-v3-turbo", "langue": "en",
                       "vocabulaire": ["CASA", "OTP", "Sébastien"]},
        live={"actif": False, "periode": 20.0, "modele": "small"},
        locuteurs={"pas_des_prenoms": ["Copernic", "Jira"], "personnes": 4},
        minutes={"moteur": "claude", "modele": "opus", "destinataire": "moi@exemple.fr"},
        email={"serveur": "smtp.office365.com", "port": 465, "utilisateur": "moi"},
        appearance={"theme": "sombre"},
    )


class TestTheRoundTrip:
    def test_everything_written_reads_back_identical(self, filled_in):
        relu = Config.model_validate(tomllib.loads(settings.render(filled_in)))
        for section in settings.SECTIONS:
            attribut = settings.SOUS_MODELE.get(section, section)
            expected = getattr(filled_in, attribut).model_dump()
            assert getattr(relu, attribut).model_dump() == expected, section

    def test_default_settings_read_back_too(self):
        rendered = settings.render(Config())
        assert Config.model_validate(tomllib.loads(rendered)) == Config()

    def test_the_toml_produced_is_readable(self, filled_in):
        """An unreadable file would only be discovered on the next command."""
        assert tomllib.loads(settings.render(filled_in))

    def test_les_accents_restent_tels_quels(self):
        """Un vocabulaire échappé rendrait l'amorce du modèle inutilisable."""
        rendered = settings.render(Config(transcription={"vocabulaire": ["Sébastien", "Noël"]}))
        assert "Sébastien" in rendered and "Noël" in rendered

    def test_quotation_marks_do_not_break_the_file(self):
        rendered = settings.render(Config(minutes={"destinataire": 'a"b'}))
        assert tomllib.loads(rendered)["compte_rendu"]["destinataire"] == 'a"b'


class TestWhatIsNeverWritten:
    def test_the_paths_are_never_frozen_in(self):
        """Freezing them is what made a machine that had moved read the old folder."""
        assert "[chemins]" not in settings.render(Config())
        assert "chemins" not in settings.SECTIONS

    def test_a_field_left_unset_is_left_out(self):
        """TOML n'a pas de « null » : écrire « personnes = None » casserait tout."""
        rendered = settings.render(Config(locuteurs={"personnes": None}))
        assert "personnes" not in rendered
        assert tomllib.loads(rendered)

    def test_the_smtp_password_has_no_place_here(self):
        """Il vient d'une variable d'environnement, jamais d'un fichier."""
        assert "mot_de_passe" not in settings.render(Config())


class TestWritingTheSettingsFile:
    def test_the_file_is_written_where_the_settings_are_read(self, tmp_path, filled_in):
        file = settings.save_settings(filled_in, folder=tmp_path / "ailleurs")
        assert file == tmp_path / "ailleurs/config.toml"
        assert Config.load(file).appearance.theme == "sombre"

    def test_the_previous_version_is_kept(self, tmp_path):
        folder = tmp_path / "c"
        settings.save_settings(Config(appearance={"theme": "clair"}), folder=folder)
        settings.save_settings(Config(appearance={"theme": "sombre"}), folder=folder)
        previous = Config.load(folder / "config.toml.precedent")
        assert previous.appearance.theme == "clair", "l'ancien réglage doit rester récupérable"
        assert Config.load(folder / "config.toml").appearance.theme == "sombre"

    def test_the_first_save_makes_no_backup(self, tmp_path):
        settings.save_settings(Config(), folder=tmp_path / "neuf")
        assert not (tmp_path / "neuf/config.toml.precedent").exists()

    def test_no_temporary_file_is_left(self, tmp_path):
        folder = tmp_path / "c"
        settings.save_settings(Config(), folder=folder)
        assert [f.name for f in folder.iterdir()] == ["config.toml"]

    def test_a_write_that_fails_destroys_nothing_existing(self, tmp_path, monkeypatch):
        """The save may fall over while a meeting is running: the file in place has to
        stay readable, and whole.
        """
        folder = tmp_path / "c"
        settings.save_settings(Config(appearance={"theme": "clair"}), folder=folder)
        avant = (folder / "config.toml").read_text(encoding="utf-8")

        def rendre_casse(_config_in):
            raise OSError("disque plein")

        monkeypatch.setattr(settings, "render", rendre_casse)
        with pytest.raises(OSError):
            settings.save_settings(Config(appearance={"theme": "sombre"}), folder=folder)
        assert (folder / "config.toml").read_text(encoding="utf-8") == avant
        assert not [f for f in folder.iterdir() if f.name.startswith(".config-")]
