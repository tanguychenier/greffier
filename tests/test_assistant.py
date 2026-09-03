"""L'assistant de première configuration, avec des réponses simulées."""

import json

from greffier import assistant, diagnostic


class DialogueSimule:
    """Rejoue une conversation écrite d'avance, et retient ce qui a été dit."""

    def __init__(self, reponses=None, confirmations=None, choix=None):
        self.reponses = list(reponses or [])
        self.confirmations = list(confirmations or [])
        self.choix = list(choix or [])
        self.affiche = []

    def demander(self, question, defaut=""):
        return self.reponses.pop(0) if self.reponses else defaut

    def confirmer(self, question, defaut=True):
        return self.confirmations.pop(0) if self.confirmations else defaut

    def afficher(self, texte):
        self.affiche.append(texte)

    def choisir(self, question, options, defaut):
        return self.choix.pop(0) if self.choix else options[defaut][0]

    def dialogue(self):
        return assistant.Dialogue(
            demander=self.demander, confirmer=self.confirmer,
            afficher=self.afficher, choisir=self.choisir,
        )

    @property
    def tout_dit(self):
        return "\n".join(self.affiche)


def machine(memoire=16.0, disque=100.0, systeme="Darwin"):
    return diagnostic.Machine(
        systeme=systeme, architecture="arm64", memoire_go=memoire,
        disque_libre_go=disque, acceleration="metal",
    )


def etat(constats=None, **infos):
    return diagnostic.Diagnostic(machine=machine(**infos), constats=constats or [])


class TestChoixDuModele:
    def test_une_machine_confortable_prend_le_grand_modele(self):
        assert machine(memoire=36).modele_conseille == "large-v3-turbo"

    def test_une_machine_modeste_prend_un_modele_plus_petit(self):
        """Proposer le plus gros partout ferait ramer la machine en réunion."""
        assert machine(memoire=6).modele_conseille == "medium"
        assert machine(memoire=2).modele_conseille == "small"

    def test_hors_macos_le_grand_modele_n_a_pas_le_meme_nom(self):
        assert machine(memoire=32, systeme="Linux").modele_conseille == "large-v3"

    def test_le_modele_retenu_entre_dans_la_configuration(self):
        simule = DialogueSimule()
        reponses = assistant.Reponses()
        assistant.etape_materiel(simule.dialogue(), etat(memoire=4), reponses)
        assert reponses.valeurs["GREFFIER_TRANSCRIPTION__MODELE"] == "medium"


class TestLivraison:
    def test_par_courriel_avec_outlook_ne_demande_aucun_mot_de_passe(self, monkeypatch):
        """Le compte est déjà authentifié : rien à stocker, et c'est mieux ainsi."""
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = DialogueSimule(confirmations=[True], reponses=["josiane@exemple.fr"])
        reponses = assistant.Reponses()
        assistant.etape_livraison(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__DESTINATAIRE"] == "josiane@exemple.fr"
        assert "GREFFIER_COURRIEL__SERVEUR" not in reponses.valeurs
        assert any("Automatisation" in action for action in reponses.a_faire)

    def test_par_courriel_sans_outlook_demande_le_serveur(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: False)
        simule = DialogueSimule(
            confirmations=[True],
            reponses=["moi@exemple.fr", "smtp.exemple.fr", "587", "moi@exemple.fr"],
        )
        reponses = assistant.Reponses()
        assistant.etape_livraison(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COURRIEL__SERVEUR"] == "smtp.exemple.fr"

    def test_le_mot_de_passe_n_est_jamais_ecrit(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: False)
        simule = DialogueSimule(
            confirmations=[True],
            reponses=["moi@exemple.fr", "smtp.exemple.fr", "587", "moi"],
        )
        reponses = assistant.Reponses()
        assistant.etape_livraison(simule.dialogue(), etat(), reponses)
        assert not any("MOT_DE_PASSE" in clef for clef in reponses.valeurs)
        assert "environnement" in simule.tout_dit

    def test_sans_courriel_on_choisit_un_dossier(self, tmp_path):
        simule = DialogueSimule(confirmations=[False], reponses=[str(tmp_path / "cr")])
        reponses = assistant.Reponses()
        assistant.etape_livraison(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_CHEMINS__DONNEES"] == str(tmp_path)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__DESTINATAIRE"] == ""


class TestRedacteur:
    def test_claude_absent_est_propose_a_l_installation(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: False)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: False)
        simule = DialogueSimule(confirmations=[False], choix=["aucun"])
        reponses = assistant.Reponses()
        assistant.etape_redacteur(simule.dialogue(), etat(), reponses)
        assert any("install" in action for action in reponses.a_faire)

    def test_claude_installe_mais_non_authentifie_est_signale(self, monkeypatch):
        """Sans cette vérification, l'échec surviendrait après une heure de
        transcription — au pire moment possible."""
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: False)
        simule = DialogueSimule(choix=["claude"])
        reponses = assistant.Reponses()
        assistant.etape_redacteur(simule.dialogue(), etat(), reponses)
        assert "aucune session" in simule.tout_dit
        assert any("claude" in action for action in reponses.a_faire)

    def test_claude_pret_est_choisi_par_defaut(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: True)
        simule = DialogueSimule()
        reponses = assistant.Reponses()
        assistant.etape_redacteur(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__MOTEUR"] == "claude"

    def test_le_modele_est_demande_et_vaut_opus_par_defaut(self, monkeypatch):
        """Le second de la gamme, pas le premier : rédiger depuis une
        transcription déjà attribuée est de la synthèse, et le haut de gamme
        rend le même document en entamant un quota bien plus vite."""
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: True)
        simule = DialogueSimule()
        reponses = assistant.Reponses()
        assistant.etape_redacteur(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__MODELE"] == "opus"
        assert assistant.MODELES_CLAUDE[0][0] == "opus", "le défaut est le premier proposé"

    def test_un_autre_modele_peut_etre_choisi(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: True)
        simule = DialogueSimule(choix=["claude", "haiku"])
        reponses = assistant.Reponses()
        assistant.etape_redacteur(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__MODELE"] == "haiku"

    def test_sans_redacteur_aucun_modele_n_est_pose(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: False)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: False)
        simule = DialogueSimule(confirmations=[False], choix=["aucun"])
        reponses = assistant.Reponses()
        assistant.etape_redacteur(simule.dialogue(), etat(), reponses)
        assert "GREFFIER_COMPTE_RENDU__MODELE" not in reponses.valeurs

    def test_les_modeles_proposes_sont_des_alias_que_claude_code_accepte(self):
        """« claude --model » attend un alias (fable, opus, sonnet) ou un nom
        complet ; un libellé de confort passé tel quel ferait échouer l'appel."""
        for clef, libelle in assistant.MODELES_CLAUDE:
            assert clef == clef.lower() and " " not in clef
            assert libelle.lower().startswith(clef)


class TestVocabulaire:
    def test_le_vocabulaire_sert_aussi_de_liste_d_exclusion(self):
        """Sans cela, « merci Copernic » créerait un participant."""
        simule = DialogueSimule(reponses=["Copernic, Kanban , Trello"])
        reponses = assistant.Reponses()
        assistant.etape_vocabulaire(simule.dialogue(), etat(), reponses)
        mots = json.loads(reponses.valeurs["GREFFIER_TRANSCRIPTION__VOCABULAIRE"])
        assert mots == ["Copernic", "Kanban", "Trello"]
        assert json.loads(reponses.valeurs["GREFFIER_LOCUTEURS__PAS_DES_PRENOMS"]) == mots

    def test_on_peut_passer(self):
        simule = DialogueSimule(reponses=[""])
        reponses = assistant.Reponses()
        assistant.etape_vocabulaire(simule.dialogue(), etat(), reponses)
        assert "GREFFIER_TRANSCRIPTION__VOCABULAIRE" not in reponses.valeurs


class TestEcriture:
    def test_le_fichier_produit_est_relisible_par_la_configuration(self, tmp_path, monkeypatch):
        """La boucle complète : l'assistant écrit, la configuration relit."""
        from greffier.config import Config

        reponses = assistant.Reponses()
        reponses.poser("GREFFIER_COMPTE_RENDU__MOTEUR", "ollama")
        reponses.poser("GREFFIER_COMPTE_RENDU__DESTINATAIRE", "moi@exemple.fr")
        cible = assistant.ecrire(reponses, tmp_path / ".env")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "vide"))
        config = Config()
        assert config.compte_rendu.moteur == "ollama"
        assert config.compte_rendu.destinataire == "moi@exemple.fr"
        assert cible.exists()

    def test_une_configuration_existante_est_conservee(self, tmp_path):
        """On ne détruit pas les réglages de quelqu'un sans laisser de trace."""
        cible = tmp_path / ".env"
        cible.write_text("GREFFIER_ANCIEN=1\n", encoding="utf-8")
        assistant.ecrire(assistant.Reponses(), cible)
        assert (tmp_path / ".env.precedent").read_text().strip() == "GREFFIER_ANCIEN=1"


class TestParcoursComplet:
    def test_du_debut_a_la_fin_sans_rien_installer(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "claude_installe", lambda: True)
        monkeypatch.setattr(diagnostic, "claude_authentifie", lambda: True)
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = DialogueSimule(
            confirmations=[True],
            reponses=["josiane@exemple.fr", "Copernic, OASIS"],
        )
        reponses = assistant.executer(simule.dialogue(), etat())
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__MOTEUR"] == "claude"
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__DESTINATAIRE"] == "josiane@exemple.fr"
        assert reponses.valeurs["GREFFIER_TRANSCRIPTION__MOTEUR"] == "whisper.cpp"
        assert "Copernic" in reponses.valeurs["GREFFIER_LOCUTEURS__PAS_DES_PRENOMS"]

    def test_un_manque_bloquant_est_annonce_avant_tout(self):
        manque = diagnostic.Constat(
            nom="ffmpeg", present=False, detail="absent",
            remede="brew install ffmpeg", bloquant=True,
        )
        simule = DialogueSimule(confirmations=[False], reponses=[""])
        reponses = assistant.executer(simule.dialogue(), etat(constats=[manque]))
        assert "brew install ffmpeg" in reponses.a_faire


class TestAdresseCourriel:
    def test_une_adresse_invalide_est_redemandee(self, monkeypatch):
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = DialogueSimule(confirmations=[True], reponses=["pas-une-adresse", "moi@ex.fr"])
        reponses = assistant.Reponses()
        assistant.etape_livraison(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__DESTINATAIRE"] == "moi@ex.fr"

    def test_sans_adresse_on_ne_pretend_pas_envoyer(self, monkeypatch):
        """Dire « oui au courriel » puis ne rien saisir produisait une
        configuration qui promettait un envoi et n'envoyait rien."""
        monkeypatch.setattr(diagnostic, "outlook_present", lambda: True)
        simule = DialogueSimule(confirmations=[True], reponses=["", "", ""])
        reponses = assistant.Reponses()
        assistant.etape_livraison(simule.dialogue(), etat(), reponses)
        assert reponses.valeurs["GREFFIER_COMPTE_RENDU__DESTINATAIRE"] == ""
        assert "restera simplement sur le disque" in simule.tout_dit
