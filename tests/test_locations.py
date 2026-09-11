"""Where the settings and the data live, system by system.

The delicate point is macOS: the native location rather than XDG, because the
hidden folders of an account are watched by the machine's guards, and a move
that loses nothing for machines installed before.
"""

import platform
from pathlib import Path

import pytest

from greffier import locations

NATIF = "Library/Application Support/Greffier"


@pytest.fixture
def a_clean_home(monkeypatch, tmp_path):
    """A clean account, with no XDG variable inherited from the machine."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


class TestMacOS:
    def test_tout_vit_dans_application_support(self, a_clean_home):
        assert locations.config_folder("Darwin") == a_clean_home / NATIF
        assert locations.data_folder("Darwin") == a_clean_home / NATIF

    def test_xdg_wins_when_it_is_set(self, a_clean_home, monkeypatch):
        """It is what isolates the tests, and what leaves the choice open."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(a_clean_home / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(a_clean_home / "xdg-donnees"))
        assert locations.config_folder("Darwin") == a_clean_home / "xdg/greffier"
        assert locations.data_folder("Darwin") == a_clean_home / "xdg-donnees/greffier"

    def test_une_ancienne_configuration_reste_servie(self, a_clean_home):
        """Un poste installé avant continue de lire sa configuration."""
        former = a_clean_home / ".config/greffier"
        former.mkdir(parents=True)
        (former / "config.toml").write_text("", encoding="utf-8")
        assert locations.config_folder("Darwin") == former

    def test_the_settings_are_judged_by_the_file_not_the_folder(self, a_clean_home):
        """The native folder exists as soon as there is data: that does not mean it holds
        any settings.
        """
        (a_clean_home / NATIF / "enregistrements").mkdir(parents=True)
        former = a_clean_home / ".config/greffier"
        former.mkdir(parents=True)
        (former / ".env").write_text("", encoding="utf-8")
        assert locations.config_folder("Darwin") == former

    def test_the_native_settings_come_before_the_old_ones(self, a_clean_home):
        for folder in (a_clean_home / NATIF, a_clean_home / ".config/greffier"):
            folder.mkdir(parents=True)
            (folder / "config.toml").write_text("", encoding="utf-8")
        assert locations.config_folder("Darwin") == a_clean_home / NATIF

    def test_d_anciennes_donnees_restent_servies(self, a_clean_home):
        former = a_clean_home / ".local/share/greffier"
        former.mkdir(parents=True)
        assert locations.data_folder("Darwin") == former

    def test_les_donnees_natives_priment(self, a_clean_home):
        (a_clean_home / ".local/share/greffier").mkdir(parents=True)
        (a_clean_home / NATIF).mkdir(parents=True)
        assert locations.data_folder("Darwin") == a_clean_home / NATIF


class TestAilleurs:
    def test_linux_suit_xdg(self, a_clean_home, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(a_clean_home / "c"))
        assert locations.config_folder("Linux") == a_clean_home / "c/greffier"
        assert locations.data_folder("Linux") == a_clean_home / ".local/share/greffier"

    def test_windows_uses_appdata(self, a_clean_home, monkeypatch):
        monkeypatch.setenv("APPDATA", str(a_clean_home / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(a_clean_home / "Local"))
        assert locations.config_folder("Windows") == a_clean_home / "Roaming/greffier"
        assert locations.data_folder("Windows") == a_clean_home / "Local/greffier"

    def test_with_no_argument_it_is_the_current_system(self, a_clean_home):
        expected = locations.config_folder(platform.system())
        assert locations.config_folder() == expected


class TestDemenagement:
    def test_anywhere_but_macos_nothing_moves(self, a_clean_home):
        (a_clean_home / ".config/greffier").mkdir(parents=True)
        assert locations.relocate("Linux") == []
        assert (a_clean_home / ".config/greffier").exists()

    def test_configuration_et_donnees_rejoignent_application_support(self, a_clean_home):
        config = a_clean_home / ".config/greffier"
        data = a_clean_home / ".local/share/greffier"
        config.mkdir(parents=True)
        (data / "modeles").mkdir(parents=True)
        (config / "config.toml").write_text("[audio]\n", encoding="utf-8")
        (config / ".env").write_text("X=1\n", encoding="utf-8")
        (data / "modeles/gros.bin").write_bytes(b"\0" * 10)

        faits = locations.relocate("Darwin")

        natif = a_clean_home / NATIF
        assert (natif / "config.toml").read_text(encoding="utf-8") == "[audio]\n"
        assert (natif / ".env").exists()
        assert (natif / "modeles/gros.bin").stat().st_size == 10
        assert not config.exists() and not data.exists(), "les dossiers vides disparaissent"
        assert {target.name for _, target in faits} == {"config.toml", ".env", "modeles"}
        # Afterwards everything resolves to the same place: nothing hidden left.
        assert locations.config_folder("Darwin") == natif
        assert locations.data_folder("Darwin") == natif

    def test_it_can_be_run_again_with_nothing_to_do(self, a_clean_home):
        assert locations.relocate("Darwin") == []
        assert not (a_clean_home / NATIF).exists(), "rien à déplacer : rien n'est créé"

    def test_it_never_overwrites_what_exists_at_the_destination(self, a_clean_home):
        natif = a_clean_home / NATIF
        natif.mkdir(parents=True)
        (natif / "config.toml").write_text("neuf", encoding="utf-8")
        former = a_clean_home / ".config/greffier"
        former.mkdir(parents=True)
        (former / "config.toml").write_text("vieux", encoding="utf-8")
        (former / "config.toml.sauvegarde").write_text("", encoding="utf-8")

        faits = locations.relocate("Darwin")

        assert (natif / "config.toml").read_text(encoding="utf-8") == "neuf"
        assert (former / "config.toml").exists(), "le conflit reste en place, visible"
        assert [target.name for _, target in faits] == ["config.toml.sauvegarde"]

    def test_xdg_set_means_hands_off(self, a_clean_home, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(a_clean_home / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(a_clean_home / "xdg-donnees"))
        (a_clean_home / ".config/greffier").mkdir(parents=True)
        (a_clean_home / ".local/share/greffier").mkdir(parents=True)
        assert locations.relocate("Darwin") == []
