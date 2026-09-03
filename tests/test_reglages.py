"""L'écriture de `config.toml` : ce qui se règle depuis la fenêtre doit se relire.

Le risque n'est pas de mal écrire une ligne, c'est d'en perdre une. Le fichier
est régénéré à chaque enregistrement : un champ oublié par le module dispa­raît
du poste, silencieusement, et la transcription suivante s'en trouve dégradée
sans que rien ne l'annonce. Ces tests éprouvent donc surtout la **fidélité de
l'aller-retour**, section par section.
"""

import tomllib

import pytest

from greffier import reglages
from greffier.config import Config


@pytest.fixture(autouse=True)
def sans_environnement(monkeypatch, tmp_path):
    """Isole du poste : sinon la configuration personnelle est lue et relue."""
    import os

    for clef in list(os.environ):
        if clef.startswith("GREFFIER_"):
            monkeypatch.delenv(clef)
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
        direct={"actif": False, "periode": 20.0, "modele": "small"},
        locuteurs={"pas_des_prenoms": ["Copernic", "Jira"], "personnes": 4},
        compte_rendu={"moteur": "claude", "modele": "opus", "destinataire": "moi@exemple.fr"},
        courriel={"serveur": "smtp.office365.com", "port": 465, "utilisateur": "moi"},
        apparence={"theme": "sombre"},
    )


class TestAllerRetour:
    def test_tout_ce_qui_est_ecrit_se_relit_identique(self, garnie):
        relu = Config.model_validate(tomllib.loads(reglages.rendre(garnie)))
        for section in reglages.SECTIONS:
            attendu = getattr(garnie, section).model_dump()
            assert getattr(relu, section).model_dump() == attendu, section

    def test_une_configuration_par_defaut_se_relit_aussi(self):
        rendu = reglages.rendre(Config())
        assert Config.model_validate(tomllib.loads(rendu)) == Config()

    def test_le_toml_produit_est_lisible(self, garnie):
        """Un fichier illisible ne serait découvert qu'à la commande suivante."""
        assert tomllib.loads(reglages.rendre(garnie))

    def test_les_accents_restent_tels_quels(self):
        """Un vocabulaire échappé rendrait l'amorce du modèle inutilisable."""
        rendu = reglages.rendre(Config(transcription={"vocabulaire": ["Sébastien", "Noël"]}))
        assert "Sébastien" in rendu and "Noël" in rendu

    def test_les_guillemets_ne_cassent_pas_le_fichier(self):
        rendu = reglages.rendre(Config(compte_rendu={"destinataire": 'a"b'}))
        assert tomllib.loads(rendu)["compte_rendu"]["destinataire"] == 'a"b'


class TestCeQuiNEstPasEcrit:
    def test_les_chemins_ne_sont_jamais_figes(self):
        """Les figer est ce qui faisait lire l'ancien dossier à un poste déménagé."""
        assert "[chemins]" not in reglages.rendre(Config())
        assert "chemins" not in reglages.SECTIONS

    def test_un_champ_non_renseigne_est_omis(self):
        """TOML n'a pas de « null » : écrire « personnes = None » casserait tout."""
        rendu = reglages.rendre(Config(locuteurs={"personnes": None}))
        assert "personnes" not in rendu
        assert tomllib.loads(rendu)

    def test_le_mot_de_passe_smtp_n_a_pas_de_place_ici(self):
        """Il vient d'une variable d'environnement, jamais d'un fichier."""
        assert "mot_de_passe" not in reglages.rendre(Config())


class TestEcriture:
    def test_le_fichier_est_ecrit_a_l_endroit_ou_la_config_est_lue(self, tmp_path, garnie):
        fichier = reglages.sauver(garnie, dossier=tmp_path / "ailleurs")
        assert fichier == tmp_path / "ailleurs/config.toml"
        assert Config.charger(fichier).apparence.theme == "sombre"

    def test_la_version_precedente_est_conservee(self, tmp_path):
        dossier = tmp_path / "c"
        reglages.sauver(Config(apparence={"theme": "clair"}), dossier=dossier)
        reglages.sauver(Config(apparence={"theme": "sombre"}), dossier=dossier)
        precedent = Config.charger(dossier / "config.toml.precedent")
        assert precedent.apparence.theme == "clair", "l'ancien réglage doit rester récupérable"
        assert Config.charger(dossier / "config.toml").apparence.theme == "sombre"

    def test_le_premier_enregistrement_ne_fabrique_pas_de_sauvegarde(self, tmp_path):
        reglages.sauver(Config(), dossier=tmp_path / "neuf")
        assert not (tmp_path / "neuf/config.toml.precedent").exists()

    def test_aucun_fichier_provisoire_ne_reste(self, tmp_path):
        dossier = tmp_path / "c"
        reglages.sauver(Config(), dossier=dossier)
        assert [f.name for f in dossier.iterdir()] == ["config.toml"]

    def test_une_ecriture_qui_echoue_ne_detruit_pas_l_existant(self, tmp_path, monkeypatch):
        """L'enregistrement peut tomber pendant qu'une réunion tourne : le
        fichier en place doit rester lisible, entier."""
        dossier = tmp_path / "c"
        reglages.sauver(Config(apparence={"theme": "clair"}), dossier=dossier)
        avant = (dossier / "config.toml").read_text(encoding="utf-8")

        def rendre_casse(_config):
            raise OSError("disque plein")

        monkeypatch.setattr(reglages, "rendre", rendre_casse)
        with pytest.raises(OSError):
            reglages.sauver(Config(apparence={"theme": "sombre"}), dossier=dossier)
        assert (dossier / "config.toml").read_text(encoding="utf-8") == avant
        assert not [f for f in dossier.iterdir() if f.name.startswith(".config-")]
