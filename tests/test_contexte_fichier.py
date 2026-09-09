"""Lire le contexte du milieu, et le compléter depuis ce qu'on sait déjà."""

from greffier.adaptateurs.contexte_fichier import (
    depuis_la_banque,
    depuis_vocabulaire,
    lire,
    poser_le_gabarit,
)


class TestLectureDuFichier:
    def test_termes_et_personnes_sont_lus(self, tmp_path):
        fichier = tmp_path / "contexte.toml"
        fichier.write_text(
            '[[termes]]\necriture = "OTP"\nsens = "mot de passe à usage unique"\n'
            '[[personnes]]\nnom = "Sophie"\nrole = "cheffe de projet"\n',
            encoding="utf-8",
        )
        contexte = lire(fichier)
        assert contexte.termes[0].ecriture == "OTP"
        assert contexte.intervenants[0].role == "cheffe de projet"

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path):
        assert lire(tmp_path / "jamais-ecrit.toml").vide

    def test_un_fichier_illisible_ne_bloque_pas_la_reunion(self, tmp_path):
        """Mieux vaut démarrer sans glossaire que refuser de démarrer."""
        fichier = tmp_path / "contexte.toml"
        fichier.write_text("[[termes]\nceci n'est pas du TOML", encoding="utf-8")
        assert lire(fichier).vide

    def test_une_entree_sans_ecriture_est_ecartee_sans_tout_perdre(self, tmp_path):
        fichier = tmp_path / "contexte.toml"
        fichier.write_text(
            '[[termes]]\nsens = "orpheline"\n[[termes]]\necriture = "CASA"\n',
            encoding="utf-8",
        )
        contexte = lire(fichier)
        assert [t.ecriture for t in contexte.termes] == ["CASA"]


class TestSourcesDeja:
    """Deux sources existaient déjà et n'étaient pas exploitées."""

    def test_le_vocabulaire_de_la_configuration_est_reprise(self):
        contexte = depuis_vocabulaire(["CASA", "OTP", "  "])
        assert [t.ecriture for t in contexte.termes] == ["CASA", "OTP"]

    def test_la_banque_de_voix_fournit_les_habitues(self):
        """Un prénom mal transcrit décide de l'attribution des tours de parole."""
        contexte = depuis_la_banque(["Kerann", "Paul", ""])
        assert [i.nom for i in contexte.intervenants] == ["Kerann", "Paul"]


class TestGabarit:
    def test_le_gabarit_est_pose_une_seule_fois(self, tmp_path):
        fichier = tmp_path / "contexte.toml"
        assert poser_le_gabarit(fichier) is True
        assert poser_le_gabarit(fichier) is False

    def test_le_gabarit_pose_est_lisible_et_utile(self, tmp_path):
        fichier = tmp_path / "contexte.toml"
        poser_le_gabarit(fichier)
        contexte = lire(fichier)
        assert not contexte.vide, "un gabarit sans exemple actif n'apprend rien"


class TestAjoutDepuisLaConversation:
    """Alimenter le contexte demandait d'ouvrir un fichier."""

    def test_un_terme_s_ajoute_avec_son_sens(self, tmp_path):
        from greffier.adaptateurs.contexte_fichier import ajouter_un_terme

        fichier = tmp_path / "contexte.toml"
        assert ajouter_un_terme(fichier, "OTP", "mot de passe à usage unique")
        terme = next(t for t in lire(fichier).termes if t.ecriture == "OTP")
        assert terme.sens == "mot de passe à usage unique"

    def test_une_personne_s_ajoute_avec_son_role(self, tmp_path):
        from greffier.adaptateurs.contexte_fichier import ajouter_une_personne

        fichier = tmp_path / "contexte.toml"
        assert ajouter_une_personne(fichier, "Morgane", "cheffe de projet")
        gens = lire(fichier).intervenants
        assert gens[-1].nom == "Morgane"
        assert gens[-1].role == "cheffe de projet"

    def test_une_personne_deja_connue_n_est_pas_doublee(self, tmp_path):
        from greffier.adaptateurs.contexte_fichier import ajouter_une_personne

        fichier = tmp_path / "contexte.toml"
        ajouter_une_personne(fichier, "Morgane", "cheffe de projet")
        assert ajouter_une_personne(fichier, "morgane") is False

    def test_les_commentaires_survivent_aux_ajouts(self, tmp_path):
        """Le fichier est édité à la main : on ajoute au bout, on ne régénère pas."""
        from greffier.adaptateurs.contexte_fichier import (
            ajouter_une_personne,
            poser_le_gabarit,
        )

        fichier = tmp_path / "contexte.toml"
        poser_le_gabarit(fichier)
        ajouter_une_personne(fichier, "Morgane", "cheffe de projet")
        assert "il faut les lui dire" in fichier.read_text(encoding="utf-8")

    def test_un_nom_vide_est_refuse(self, tmp_path):
        from greffier.adaptateurs.contexte_fichier import ajouter_une_personne

        assert ajouter_une_personne(tmp_path / "contexte.toml", "  ") is False
