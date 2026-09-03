"""La configuration : valeurs par défaut, .env, environnement, TOML."""

from pathlib import Path

import pytest

from greffier.config import Config


@pytest.fixture(autouse=True)
def sans_environnement(monkeypatch, tmp_path):
    """Isole chaque test du poste sur lequel il tourne.

    Sans cela, la configuration personnelle du développeur — celle qui vit dans
    ~/.config/greffier — est lue par la source TOML et les tests passent ou
    échouent selon la machine.
    """
    import os

    for clef in list(os.environ):
        if clef.startswith("GREFFIER_"):
            monkeypatch.delenv(clef)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)


class TestValeursParDefaut:
    def test_claude_redige_par_defaut(self):
        """Choix explicite : la synthèse d'un compte rendu dépasse ce qu'un
        modèle de portable sait faire. Seul maillon non local, assumé."""
        assert Config().compte_rendu.moteur == "claude"

    def test_un_poste_sans_configuration_fonctionne(self):
        config = Config()
        assert config.transcription.langue == "fr"
        assert config.audio.duree_maximale == 14_400
        assert config.locuteurs.personnes is None

    def test_le_vocabulaire_vide_ne_produit_pas_d_amorce(self):
        assert Config().transcription.amorce == ""

    def test_le_vocabulaire_devient_une_amorce(self):
        config = Config(transcription={"vocabulaire": ["Jira", "recette"]})
        assert "Jira, recette" in config.transcription.amorce


class TestModeleDuRedacteur:
    """Quel modèle rédige, et pourquoi ce n'est pas le plus puissant."""

    def test_claude_prend_le_second_de_la_gamme_par_defaut(self):
        """Rédiger depuis une transcription déjà attribuée est de la synthèse :
        le haut de gamme rend le même document en entamant un quota bien plus
        vite. Le choix reste offert, dans les deux sens."""
        assert Config().compte_rendu.modele_effectif == "opus"

    def test_le_reglage_explicite_l_emporte(self):
        config = Config(compte_rendu={"moteur": "claude", "modele": "fable"})
        assert config.compte_rendu.modele_effectif == "fable"

    def test_ollama_a_son_propre_defaut(self):
        """Un alias Claude Code n'a aucun sens pour Ollama, et l'inverse non plus."""
        assert Config(compte_rendu={"moteur": "ollama"}).compte_rendu.modele_effectif == "qwen3:8b"

    def test_sans_redacteur_il_n_y_a_pas_de_modele(self):
        assert Config(compte_rendu={"moteur": "aucun"}).compte_rendu.modele_effectif == ""

    def test_le_modele_se_regle_par_l_environnement(self):
        """Pour forcer le temps d'une commande, sans toucher au fichier."""
        import os

        os.environ["GREFFIER_COMPTE_RENDU__MODELE"] = "sonnet"
        try:
            assert Config().compte_rendu.modele_effectif == "sonnet"
        finally:
            del os.environ["GREFFIER_COMPTE_RENDU__MODELE"]


class TestLangue:
    """Le code de langue, et ce que veut dire son absence."""

    def test_le_francais_par_defaut(self):
        """L'annoncer vaut mieux que la faire deviner quand on la connaît."""
        assert Config().transcription.langue == "fr"

    def test_vide_veut_dire_detection_automatique(self):
        """Même convention que le micro vide : on laisse la machine décider."""
        assert Config(transcription={"langue": ""}).transcription.langue == ""


class TestApparence:
    def test_le_theme_suit_le_systeme_par_defaut(self):
        """Une application qui impose son goût jure avec le reste de l'écran."""
        assert Config().apparence.theme == "systeme"

    def test_le_theme_se_force(self):
        assert Config(apparence={"theme": "sombre"}).apparence.theme == "sombre"


class TestSourcesDeConfiguration:
    def test_l_environnement_prime(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_COMPTE_RENDU__MOTEUR", "ollama")
        assert Config().compte_rendu.moteur == "ollama"

    def test_un_fichier_env_est_lu(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text(
            "GREFFIER_COMPTE_RENDU__DESTINATAIRE=moi@exemple.fr\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        assert Config().compte_rendu.destinataire == "moi@exemple.fr"

    def test_l_environnement_l_emporte_sur_le_fichier_env(self, tmp_path, monkeypatch):
        """On doit pouvoir forcer un réglage le temps d'une commande."""
        (tmp_path / ".env").write_text("GREFFIER_COMPTE_RENDU__MOTEUR=claude\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GREFFIER_COMPTE_RENDU__MOTEUR", "aucun")
        assert Config().compte_rendu.moteur == "aucun"

    def test_les_listes_se_donnent_en_json(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_LOCUTEURS__PAS_DES_PRENOMS", '["Copernic","Trello"]')
        assert Config().locuteurs.pas_des_prenoms == ["Copernic", "Trello"]

    def test_un_fichier_toml_explicite_est_lu(self, tmp_path):
        fichier = tmp_path / "config.toml"
        fichier.write_text(
            '[compte_rendu]\nmoteur = "ollama"\nmodele = "qwen3:8b"\n', encoding="utf-8"
        )
        config = Config.charger(fichier)
        assert (config.compte_rendu.moteur, config.compte_rendu.modele) == ("ollama", "qwen3:8b")

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path):
        """Cas d'un poste qui vient d'installer."""
        assert Config.charger(tmp_path / "nulle-part.toml").compte_rendu.moteur == "claude"

    def test_un_fichier_illisible_est_une_erreur(self, tmp_path):
        """Mieux vaut le dire qu'appliquer autre chose que ce qui est écrit."""
        fichier = tmp_path / "casse.toml"
        fichier.write_text("[compte_rendu\nmoteur =", encoding="utf-8")
        with pytest.raises(ValueError, match="illisible"):
            Config.charger(fichier)


class TestChemins:
    def test_les_sous_dossiers_derivent_des_donnees(self, tmp_path):
        config = Config(chemins={"donnees": tmp_path})
        assert config.chemins.enregistrements == tmp_path / "enregistrements"
        assert config.chemins.banque_de_voix == tmp_path / "banque-de-voix"

    def test_le_chemin_des_donnees_est_configurable(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_CHEMINS__DONNEES", "/ailleurs")
        assert Config().chemins.donnees == Path("/ailleurs")
