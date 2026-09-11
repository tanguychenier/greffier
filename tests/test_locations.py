"""Où vivent configuration et données, système par système.

Le point délicat est macOS : l'emplacement natif plutôt que XDG, parce que les
dossiers cachés du compte sont surveillés par les gardes du poste, et un
déménagement qui ne perd rien pour les postes installés avant.
"""

import platform
from pathlib import Path

import pytest

from greffier import locations

NATIF = "Library/Application Support/Greffier"


@pytest.fixture
def maison(monkeypatch, tmp_path):
    """Un compte vierge, sans variable XDG héritée du poste."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


class TestMacOS:
    def test_tout_vit_dans_application_support(self, maison):
        assert locations.config_folder("Darwin") == maison / NATIF
        assert locations.data_folder("Darwin") == maison / NATIF

    def test_xdg_l_emporte_s_il_est_pose(self, maison, monkeypatch):
        """C'est ce qui isole les tests, et ce qui laisse le choix."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(maison / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(maison / "xdg-donnees"))
        assert locations.config_folder("Darwin") == maison / "xdg/greffier"
        assert locations.data_folder("Darwin") == maison / "xdg-donnees/greffier"

    def test_une_ancienne_configuration_reste_servie(self, maison):
        """Un poste installé avant continue de lire sa configuration."""
        former = maison / ".config/greffier"
        former.mkdir(parents=True)
        (former / "config.toml").write_text("", encoding="utf-8")
        assert locations.config_folder("Darwin") == former

    def test_la_configuration_se_juge_au_fichier_pas_au_dossier(self, maison):
        """Le dossier natif existe dès qu'il y a des données : ce n'est pas
        pour autant qu'il contient une configuration."""
        (maison / NATIF / "enregistrements").mkdir(parents=True)
        former = maison / ".config/greffier"
        former.mkdir(parents=True)
        (former / ".env").write_text("", encoding="utf-8")
        assert locations.config_folder("Darwin") == former

    def test_la_configuration_native_prime_sur_l_ancienne(self, maison):
        for folder in (maison / NATIF, maison / ".config/greffier"):
            folder.mkdir(parents=True)
            (folder / "config.toml").write_text("", encoding="utf-8")
        assert locations.config_folder("Darwin") == maison / NATIF

    def test_d_anciennes_donnees_restent_servies(self, maison):
        former = maison / ".local/share/greffier"
        former.mkdir(parents=True)
        assert locations.data_folder("Darwin") == former

    def test_les_donnees_natives_priment(self, maison):
        (maison / ".local/share/greffier").mkdir(parents=True)
        (maison / NATIF).mkdir(parents=True)
        assert locations.data_folder("Darwin") == maison / NATIF


class TestAilleurs:
    def test_linux_suit_xdg(self, maison, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(maison / "c"))
        assert locations.config_folder("Linux") == maison / "c/greffier"
        assert locations.data_folder("Linux") == maison / ".local/share/greffier"

    def test_windows_uses_appdata(self, maison, monkeypatch):
        monkeypatch.setenv("APPDATA", str(maison / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(maison / "Local"))
        assert locations.config_folder("Windows") == maison / "Roaming/greffier"
        assert locations.data_folder("Windows") == maison / "Local/greffier"

    def test_sans_argument_c_est_le_systeme_courant(self, maison):
        expected = locations.config_folder(platform.system())
        assert locations.config_folder() == expected


class TestDemenagement:
    def test_ailleurs_que_sur_macos_rien_ne_bouge(self, maison):
        (maison / ".config/greffier").mkdir(parents=True)
        assert locations.relocate("Linux") == []
        assert (maison / ".config/greffier").exists()

    def test_configuration_et_donnees_rejoignent_application_support(self, maison):
        config = maison / ".config/greffier"
        data = maison / ".local/share/greffier"
        config.mkdir(parents=True)
        (data / "modeles").mkdir(parents=True)
        (config / "config.toml").write_text("[audio]\n", encoding="utf-8")
        (config / ".env").write_text("X=1\n", encoding="utf-8")
        (data / "modeles/gros.bin").write_bytes(b"\0" * 10)

        faits = locations.relocate("Darwin")

        natif = maison / NATIF
        assert (natif / "config.toml").read_text(encoding="utf-8") == "[audio]\n"
        assert (natif / ".env").exists()
        assert (natif / "modeles/gros.bin").stat().st_size == 10
        assert not config.exists() and not data.exists(), "les dossiers vides disparaissent"
        assert {target.name for _, target in faits} == {"config.toml", ".env", "modeles"}
        # Après coup, tout se résout au même endroit : plus rien de caché.
        assert locations.config_folder("Darwin") == natif
        assert locations.data_folder("Darwin") == natif

    def test_relancable_sans_rien_a_faire(self, maison):
        assert locations.relocate("Darwin") == []
        assert not (maison / NATIF).exists(), "rien à déplacer : rien n'est créé"

    def test_n_ecrase_jamais_ce_qui_existe_a_destination(self, maison):
        natif = maison / NATIF
        natif.mkdir(parents=True)
        (natif / "config.toml").write_text("neuf", encoding="utf-8")
        former = maison / ".config/greffier"
        former.mkdir(parents=True)
        (former / "config.toml").write_text("vieux", encoding="utf-8")
        (former / "config.toml.sauvegarde").write_text("", encoding="utf-8")

        faits = locations.relocate("Darwin")

        assert (natif / "config.toml").read_text(encoding="utf-8") == "neuf"
        assert (former / "config.toml").exists(), "le conflit reste en place, visible"
        assert [target.name for _, target in faits] == ["config.toml.sauvegarde"]

    def test_xdg_pose_veut_dire_pas_touche(self, maison, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(maison / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(maison / "xdg-donnees"))
        (maison / ".config/greffier").mkdir(parents=True)
        (maison / ".local/share/greffier").mkdir(parents=True)
        assert locations.relocate("Darwin") == []
