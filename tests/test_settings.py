"""L'écriture de `config.toml` : ce qui se règle depuis la fenêtre doit se relire.

Le risque n'est pas de mal écrire une ligne, c'est d'en perdre une. Le fichier
est régénéré à chaque enregistrement : un champ oublié par le module dispa­raît
du poste, silencieusement, et la transcription suivante s'en trouve dégradée
sans que rien ne l'annonce. Ces tests éprouvent donc surtout la **fidélité de
l'aller-retour**, section par section.
"""

import tomllib

import pytest

from greffier.adapters import configuration as settings
from greffier.adapters.configuration import Config


@pytest.fixture(autouse=True)
def without_an_environment(monkeypatch, tmp_path):
    """Isole du poste : sinon la configuration personnelle est lue et relue."""
    import os

    for key in list(os.environ):
        if key.startswith("GREFFIER_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def garnie():
    """Une configuration dont chaque section porte autre chose que le défaut."""
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
    def test_tout_ce_qui_est_ecrit_se_relit_identique(self, garnie):
        relu = Config.model_validate(tomllib.loads(settings.render(garnie)))
        for section in settings.SECTIONS:
            attribut = settings.SOUS_MODELE.get(section, section)
            expected = getattr(garnie, attribut).model_dump()
            assert getattr(relu, attribut).model_dump() == expected, section

    def test_une_configuration_par_defaut_se_relit_aussi(self):
        rendered = settings.render(Config())
        assert Config.model_validate(tomllib.loads(rendered)) == Config()

    def test_le_toml_produit_est_lisible(self, garnie):
        """Un fichier illisible ne serait découvert qu'à la commande suivante."""
        assert tomllib.loads(settings.render(garnie))

    def test_les_accents_restent_tels_quels(self):
        """Un vocabulaire échappé rendrait l'amorce du modèle inutilisable."""
        rendered = settings.render(Config(transcription={"vocabulaire": ["Sébastien", "Noël"]}))
        assert "Sébastien" in rendered and "Noël" in rendered

    def test_les_guillemets_ne_cassent_pas_le_fichier(self):
        rendered = settings.render(Config(minutes={"destinataire": 'a"b'}))
        assert tomllib.loads(rendered)["compte_rendu"]["destinataire"] == 'a"b'


class TestCeQuiNEstPasEcrit:
    def test_les_chemins_ne_sont_jamais_figes(self):
        """Les figer est ce qui faisait lire l'ancien dossier à un poste déménagé."""
        assert "[chemins]" not in settings.render(Config())
        assert "chemins" not in settings.SECTIONS

    def test_un_champ_non_renseigne_est_omis(self):
        """TOML n'a pas de « null » : écrire « personnes = None » casserait tout."""
        rendered = settings.render(Config(locuteurs={"personnes": None}))
        assert "personnes" not in rendered
        assert tomllib.loads(rendered)

    def test_le_mot_de_passe_smtp_n_a_pas_de_place_ici(self):
        """Il vient d'une variable d'environnement, jamais d'un fichier."""
        assert "mot_de_passe" not in settings.render(Config())


class TestWritingTheSettingsFile:
    def test_le_fichier_est_ecrit_a_l_endroit_ou_la_config_est_lue(self, tmp_path, garnie):
        file = settings.save_settings(garnie, folder=tmp_path / "ailleurs")
        assert file == tmp_path / "ailleurs/config.toml"
        assert Config.load(file).appearance.theme == "sombre"

    def test_la_version_precedente_est_conservee(self, tmp_path):
        folder = tmp_path / "c"
        settings.save_settings(Config(appearance={"theme": "clair"}), folder=folder)
        settings.save_settings(Config(appearance={"theme": "sombre"}), folder=folder)
        previous = Config.load(folder / "config.toml.precedent")
        assert previous.appearance.theme == "clair", "l'ancien réglage doit rester récupérable"
        assert Config.load(folder / "config.toml").appearance.theme == "sombre"

    def test_le_premier_enregistrement_ne_fabrique_pas_de_sauvegarde(self, tmp_path):
        settings.save_settings(Config(), folder=tmp_path / "neuf")
        assert not (tmp_path / "neuf/config.toml.precedent").exists()

    def test_aucun_fichier_provisoire_ne_reste(self, tmp_path):
        folder = tmp_path / "c"
        settings.save_settings(Config(), folder=folder)
        assert [f.name for f in folder.iterdir()] == ["config.toml"]

    def test_une_ecriture_qui_echoue_ne_detruit_pas_l_existant(self, tmp_path, monkeypatch):
        """L'enregistrement peut tomber pendant qu'une réunion tourne : le
        fichier en place doit rester lisible, entier."""
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
