"""L'assistant de première configuration, avec des réponses simulées."""

import json

from greffier.adapters import assistant_terminal as assistant
from greffier.adapters import system_diagnostic as diagnostic


class ScriptedDialogue:
    """Rejoue une conversation écrite d'avance, et retient ce qui a été dit."""

    def __init__(self, answers=None, confirmations=None, choix=None):
        self.answers = list(answers or [])
        self.confirmations = list(confirmations or [])
        self.choix = list(choix or [])
        self.affiche = []

    def ask(self, question, defaut=""):
        return self.answers.pop(0) if self.answers else defaut

    def confirmer(self, question, defaut=True):
        return self.confirmations.pop(0) if self.confirmations else defaut

    def show(self, text):
        self.affiche.append(text)

    def choose(self, question, options, defaut):
        return self.choix.pop(0) if self.choix else options[defaut][0]

    def dialogue(self):
        return assistant.Dialogue(
            ask=self.ask, confirmer=self.confirmer,
            show=self.show, choose=self.choose,
        )

    @property
    def tout_dit(self):
        return "\n".join(self.affiche)


def recorder(memoire=16.0, disque=100.0, system="Darwin"):
    return diagnostic.Recorder(
        system=system, architecture="arm64", memory_gb=memoire,
        disque_libre_go=disque, speedup="metal",
    )


def state(constats=None, **infos):
    return diagnostic.Diagnostic(recorder=recorder(**infos), constats=constats or [])


class TestChoixDuModele:
    def test_une_machine_confortable_prend_le_grand_modele(self):
        assert recorder(memoire=36).advised_model == "large-v3-turbo"

    def test_une_machine_modeste_prend_un_modele_plus_petit(self):
        """Proposer le plus gros partout ferait ramer la machine en réunion."""
        assert recorder(memoire=6).advised_model == "medium"
        assert recorder(memoire=2).advised_model == "small"

    def test_hors_macos_le_grand_modele_n_a_pas_le_meme_nom(self):
        assert recorder(memoire=32, system="Linux").advised_model == "large-v3"

    def test_le_modele_retenu_entre_dans_la_configuration(self):
        simule = ScriptedDialogue()
        answers = assistant.Answers()
        assistant.hardware_step(simule.dialogue(), state(memoire=4), answers)
        assert answers.values["GREFFIER_TRANSCRIPTION__MODEL"] == "medium"


class TestLivraison:
    def test_par_courriel_avec_outlook_ne_demande_aucun_mot_de_passe(self, monkeypatch):
        """Le compte est déjà authentifié : rien à stocker, et c'est mieux ainsi."""
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(confirmations=[True], answers=["josiane@exemple.fr"])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == "josiane@exemple.fr"
        assert "GREFFIER_EMAIL__SERVER" not in answers.values
        assert any("Automatisation" in action for action in answers.to_do)

    def test_par_courriel_sans_outlook_demande_le_serveur(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: False)
        simule = ScriptedDialogue(
            confirmations=[True],
            answers=["moi@exemple.fr", "smtp.exemple.fr", "587", "moi@exemple.fr"],
        )
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_EMAIL__SERVER"] == "smtp.exemple.fr"

    def test_le_mot_de_passe_n_est_jamais_ecrit(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: False)
        simule = ScriptedDialogue(
            confirmations=[True],
            answers=["moi@exemple.fr", "smtp.exemple.fr", "587", "moi"],
        )
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert not any("MOT_DE_PASSE" in key for key in answers.values)
        assert "environnement" in simule.tout_dit

    def test_sans_courriel_on_choisit_un_dossier(self, tmp_path):
        simule = ScriptedDialogue(confirmations=[False], answers=[str(tmp_path / "cr")])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_PATHS__DATA"] == str(tmp_path)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == ""


class TestRedacteur:
    def test_claude_absent_est_propose_a_l_installation(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: False)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: False)
        simule = ScriptedDialogue(confirmations=[False], choix=["aucun"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert any("install" in action for action in answers.to_do)

    def test_claude_installe_mais_non_authentifie_est_signale(self, monkeypatch):
        """Sans cette vérification, l'échec surviendrait après une heure de
        transcription — au pire moment possible."""
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: False)
        simule = ScriptedDialogue(choix=["claude"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert "aucune session" in simule.tout_dit
        assert any("claude" in action for action in answers.to_do)

    def test_claude_pret_est_choisi_par_defaut(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        simule = ScriptedDialogue()
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__ENGINE"] == "claude"

    def test_le_modele_est_demande_et_vaut_opus_par_defaut(self, monkeypatch):
        """Le second de la gamme, pas le premier : rédiger depuis une
        transcription déjà attribuée est de la synthèse, et le haut de gamme
        rend le même document en entamant un quota bien plus vite."""
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        simule = ScriptedDialogue()
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__MODEL"] == "opus"
        assert assistant.MODELES_CLAUDE[0][0] == "opus", "le défaut est le premier proposé"

    def test_un_autre_modele_peut_etre_choisi(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: True)
        simule = ScriptedDialogue(choix=["claude", "haiku"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__MODEL"] == "haiku"

    def test_sans_redacteur_aucun_modele_n_est_pose(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: False)
        monkeypatch.setattr(diagnostic, "claude_signed_in", lambda: False)
        simule = ScriptedDialogue(confirmations=[False], choix=["aucun"])
        answers = assistant.Answers()
        assistant.writer_step(simule.dialogue(), state(), answers)
        assert "GREFFIER_MINUTES__MODEL" not in answers.values

    def test_les_modeles_proposes_sont_des_alias_que_claude_code_accepte(self):
        """« claude --model » attend un alias (fable, opus, sonnet) ou un nom
        complet ; un libellé de confort passé tel quel ferait échouer l'appel."""
        for key, label_text in assistant.MODELES_CLAUDE:
            assert key == key.lower() and " " not in key
            assert label_text.lower().startswith(key)


class TestVocabulaire:
    def test_le_vocabulaire_sert_aussi_de_liste_d_exclusion(self):
        """Sans cela, « merci Copernic » créerait un participant."""
        simule = ScriptedDialogue(answers=["Copernic, Kanban , Trello"])
        answers = assistant.Answers()
        assistant.vocabulary_step(simule.dialogue(), state(), answers)
        words = json.loads(answers.values["GREFFIER_TRANSCRIPTION__VOCABULARY"])
        assert words == ["Copernic", "Kanban", "Trello"]
        assert json.loads(answers.values["GREFFIER_SPEAKERS__NOT_FIRST_NAMES"]) == words

    def test_on_peut_passer(self):
        simule = ScriptedDialogue(answers=[""])
        answers = assistant.Answers()
        assistant.vocabulary_step(simule.dialogue(), state(), answers)
        assert "GREFFIER_TRANSCRIPTION__VOCABULARY" not in answers.values


class TestEcriture:
    def test_le_fichier_produit_est_relisible_par_la_configuration(self, tmp_path, monkeypatch):
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

    def test_une_configuration_existante_est_conservee(self, tmp_path):
        """On ne détruit pas les réglages de quelqu'un sans laisser de trace."""
        target = tmp_path / ".env"
        target.write_text("GREFFIER_ANCIEN=1\n", encoding="utf-8")
        assistant.write(assistant.Answers(), target)
        assert (tmp_path / ".env.precedent").read_text().strip() == "GREFFIER_ANCIEN=1"


class TestParcoursComplet:
    def test_du_debut_a_la_fin_sans_rien_installer(self, monkeypatch):
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

    def test_un_manque_bloquant_est_annonce_avant_tout(self):
        manque = diagnostic.Reading(
            name="ffmpeg", present=False, detail="absent",
            remede="brew install ffmpeg", bloquant=True,
        )
        simule = ScriptedDialogue(confirmations=[False], answers=[""])
        answers = assistant.run_chain(simule.dialogue(), state(constats=[manque]))
        assert "brew install ffmpeg" in answers.to_do


class TestAdresseCourriel:
    def test_une_adresse_invalide_est_redemandee(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(confirmations=[True], answers=["pas-une-adresse", "moi@ex.fr"])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == "moi@ex.fr"

    def test_sans_adresse_on_ne_pretend_pas_envoyer(self, monkeypatch):
        """Dire « oui au courriel » puis ne rien saisir produisait une
        configuration qui promettait un envoi et n'envoyait rien."""
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = ScriptedDialogue(confirmations=[True], answers=["", "", ""])
        answers = assistant.Answers()
        assistant.delivery_step(simule.dialogue(), state(), answers)
        assert answers.values["GREFFIER_MINUTES__RECIPIENT"] == ""
        assert "restera simplement sur le disque" in simule.tout_dit
