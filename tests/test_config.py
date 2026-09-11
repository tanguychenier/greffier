"""La configuration : valeurs par défaut, .env, environnement, TOML."""

from pathlib import Path

import pytest

from greffier.adapters.configuration import Config


@pytest.fixture(autouse=True)
def without_an_environment(monkeypatch, tmp_path):
    """Isole chaque test du poste sur lequel il tourne.

    Sans cela, la configuration personnelle du développeur — celle qui vit dans
    ~/.config/greffier — est lue par la source TOML et les tests passent ou
    échouent selon la machine.
    """
    import os

    for key in list(os.environ):
        if key.startswith("GREFFIER_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)


class TestValeursParDefaut:
    def test_claude_redige_par_defaut(self):
        """Choix explicite : la synthèse d'un compte rendu dépasse ce qu'un
        modèle de portable sait faire. Seul maillon non local, assumé."""
        assert Config().minutes.engine == "claude"

    def test_un_poste_sans_configuration_fonctionne(self):
        config = Config()
        assert config.transcription.language == "fr"
        assert config.audio.maximum_length == 14_400
        assert config.speakers.people is None

    def test_le_vocabulaire_vide_ne_produit_pas_d_amorce(self):
        assert Config().transcription.prompt_seed == ""

    def test_le_vocabulaire_devient_une_amorce(self):
        config = Config(transcription={"vocabulaire": ["Jira", "recette"]})
        assert "Jira, recette" in config.transcription.prompt_seed


class TestModeleDuRedacteur:
    """Quel modèle rédige, et pourquoi ce n'est pas le plus puissant."""

    def test_claude_prend_le_second_de_la_gamme_par_defaut(self):
        """Rédiger depuis une transcription déjà attribuée est de la synthèse :
        le haut de gamme rend le même document en entamant un quota bien plus
        vite. Le choix reste offert, dans les deux sens."""
        assert Config().minutes.effective_model == "opus"

    def test_le_reglage_explicite_l_emporte(self):
        config = Config(minutes={"moteur": "claude", "modele": "fable"})
        assert config.minutes.effective_model == "fable"

    def test_ollama_a_son_propre_defaut(self):
        """Un alias Claude Code n'a aucun sens pour Ollama, et l'inverse non plus."""
        assert Config(minutes={"moteur": "ollama"}).minutes.effective_model == "qwen3:8b"

    def test_sans_redacteur_il_n_y_a_pas_de_modele(self):
        assert Config(minutes={"moteur": "aucun"}).minutes.effective_model == ""

    def test_le_modele_se_regle_par_l_environnement(self):
        """Pour forcer le temps d'une commande, sans toucher au fichier."""
        import os

        os.environ["GREFFIER_MINUTES__MODEL"] = "sonnet"
        try:
            assert Config().minutes.effective_model == "sonnet"
        finally:
            del os.environ["GREFFIER_MINUTES__MODEL"]


class TestLangue:
    """Le code de langue, et ce que veut dire son absence."""

    def test_le_francais_par_defaut(self):
        """L'annoncer vaut mieux que la faire deviner quand on la connaît."""
        assert Config().transcription.language == "fr"

    def test_vide_veut_dire_detection_automatique(self):
        """Même convention que le micro vide : on laisse la machine décider."""
        assert Config(transcription={"langue": ""}).transcription.language == ""


class TestApparence:
    def test_le_theme_suit_le_systeme_par_defaut(self):
        """Une application qui impose son goût jure avec le reste de l'écran."""
        assert Config().appearance.theme == "systeme"

    def test_le_theme_se_force(self):
        assert Config(appearance={"theme": "sombre"}).appearance.theme == "sombre"


class TestSourcesDeConfiguration:
    def test_l_environnement_prime(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_MINUTES__ENGINE", "ollama")
        assert Config().minutes.engine == "ollama"

    def test_un_fichier_env_est_lu(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text(
            "GREFFIER_MINUTES__RECIPIENT=moi@exemple.fr\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        assert Config().minutes.recipient == "moi@exemple.fr"

    def test_l_environnement_l_emporte_sur_le_fichier_env(self, tmp_path, monkeypatch):
        """On doit pouvoir forcer un réglage le temps d'une commande."""
        (tmp_path / ".env").write_text("GREFFIER_MINUTES__ENGINE=claude\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GREFFIER_MINUTES__ENGINE", "aucun")
        assert Config().minutes.engine == "aucun"

    def test_les_listes_se_donnent_en_json(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_SPEAKERS__NOT_FIRST_NAMES", '["Copernic","Trello"]')
        assert Config().speakers.not_first_names == ["Copernic", "Trello"]

    def test_un_fichier_toml_explicite_est_lu(self, tmp_path):
        file = tmp_path / "config.toml"
        file.write_text(
            '[compte_rendu]\nmoteur = "ollama"\nmodele = "qwen3:8b"\n', encoding="utf-8"
        )
        config = Config.load(file)
        assert (config.minutes.engine, config.minutes.model) == ("ollama", "qwen3:8b")

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path):
        """Cas d'un poste qui vient d'installer."""
        assert Config.load(tmp_path / "nulle-part.toml").minutes.engine == "claude"

    def test_un_fichier_illisible_est_une_erreur(self, tmp_path):
        """Mieux vaut le dire qu'appliquer autre chose que ce qui est écrit."""
        file = tmp_path / "casse.toml"
        file.write_text("[compte_rendu\nmoteur =", encoding="utf-8")
        with pytest.raises(ValueError, match="illisible"):
            Config.load(file)


class TestChemins:
    def test_les_sous_dossiers_derivent_des_donnees(self, tmp_path):
        config = Config(paths={"donnees": tmp_path})
        assert config.paths.recordings == tmp_path / "enregistrements"
        assert config.paths.voice_bank == tmp_path / "banque-de-voix"

    def test_le_chemin_des_donnees_est_configurable(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_PATHS__DATA", "/ailleurs")
        assert Config().paths.data == Path("/ailleurs")


class TestLAssistantEstActifParDefaut:
    """Il suit la réunion et répond : c'est son travail.

    Le jour où l'interface a cessé d'exposer ce réglage — un seul bouton, pour
    la voix — plus rien ne permettait de l'activer. L'assistant ne répondait pas
    et personne ne pouvait savoir pourquoi. Constaté en réunion, ce qui est le
    pire moment.
    """

    def test_il_est_actif_sans_rien_regler(self):
        from greffier.adapters.configuration import Config

        assert Config().assistant.active

    def test_mais_il_ne_parle_pas_de_lui_meme(self):
        """Répondre est sans risque ; parler de soi-même se décide."""
        from greffier.adapters.configuration import Config

        assistant = Config().assistant
        assert not assistant.initiative
        assert not assistant.demander_les_voix


class TestPrenomsEprouves:
    """Une liste et non un champ libre.

    Un prénom saisi au hasard n'est pas forcément rendu par le modèle de
    transcription, et rien ne le dirait à celui qui l'a tapé : il appellerait
    dans le vide. Chacun de ceux-ci a passé quatre épreuves — deux tournures,
    deux voix de synthèse — et cinq pièges, des phrases sans le prénom.
    """

    def test_chaque_prenom_porte_une_voix(self):
        from greffier.adapters.configuration import FIRST_NAMES, KINDS

        assert FIRST_NAMES, "la liste est vide"
        assert all(speaker_index in KINDS for speaker_index in FIRST_NAMES.values())

    def test_les_deux_genres_sont_proposés(self):
        """Sinon le choix n'en est pas un."""
        from greffier.adapters.configuration import FIRST_NAMES

        assert set(FIRST_NAMES.values()) == {0, 1}

    def test_le_prenom_pose_sa_voix(self):
        from greffier.adapters.configuration import AssistantSettings

        assert AssistantSettings(name="Lucie").effective_speaker == 0
        assert AssistantSettings(name="Martin").effective_speaker == 1

    def test_un_prenom_hors_liste_garde_le_reglage(self):
        """Le fichier de configuration autorise un prénom libre."""
        from greffier.adapters.configuration import AssistantSettings

        assert AssistantSettings(name="Aurélien", speaker_index=1).effective_speaker == 1

    def test_aucun_prenom_ecarte_ne_traine_dans_la_liste(self):
        """« Élise » se déclenche sur « elle a lu ci et ça », mesuré.

        « Greffier » lui-même est écarté pour la même raison : « le greffe du
        tribunal » suffisait à l'appeler.
        """
        from greffier.adapters.configuration import FIRST_NAMES

        assert "Élise" not in FIRST_NAMES
        assert "Greffier" not in FIRST_NAMES

    def test_chaque_prenom_se_reconnait_lui_meme(self):
        """Le contrôle minimal : la règle d'appel doit le voir dans une phrase."""
        from greffier.adapters.configuration import FIRST_NAMES
        from greffier.domain.participation import called_by_name

        for first_name in FIRST_NAMES:
            assert called_by_name(f"{first_name}, tu peux noter ça ?", first_name), first_name

    def test_aucun_prenom_ne_se_declenche_sur_une_phrase_ordinaire(self):
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


class TestLesClefsDuFichierNeBougentPas:
    """Le fichier de configuration des postes doit rester lisible.

    Chaque champ porte un `validation_alias` : le nom du champ en Python peut
    passer à l'anglais sans que la clef du fichier change. Une mise à jour qui
    rendrait illisible le `config.toml` d'un poste effacerait ses réglages en
    silence, et il n'y a pas de raison de le faire subir à qui que ce soit.
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

    def test_chaque_section_est_relue(self, tmp_path):
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

    def test_les_clefs_reecrites_sont_les_memes(self, tmp_path):
        """Ce qui est réécrit doit pouvoir être relu : c'est le vrai cycle."""
        from greffier.adapters.configuration import Config, render

        rendered = render(self._config_in(tmp_path))
        deuxieme = tmp_path / "encore.toml"
        deuxieme.write_text(rendered, encoding="utf-8")
        relu = Config.load(deuxieme)
        assert relu.assistant.name == "Lucie"
        assert relu.minutes.recipient == "moi@exemple.fr"
        assert relu.appearance.theme == "sombre"

    def test_une_clef_inconnue_ne_fait_pas_tomber(self, tmp_path):
        """Un réglage retiré d'une version à l'autre ne doit rien casser."""
        from greffier.adapters.configuration import Config

        file = tmp_path / "config.toml"
        file.write_text('[assistant]\nnom = "Alice"\nreglage_disparu = 3\n',
                           encoding="utf-8")
        assert Config.load(file).assistant.name == "Alice"
