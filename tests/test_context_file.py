"""Lire le contexte du milieu, et le compléter depuis ce qu'on sait déjà."""

from greffier.adapters.context_file import (
    from_the_bank,
    from_vocabulary,
    lay_the_template,
    read,
)


class TestLectureDuFichier:
    def test_termes_et_personnes_sont_lus(self, tmp_path):
        file = tmp_path / "contexte.toml"
        file.write_text(
            '[[termes]]\necriture = "OTP"\nsens = "mot de passe à usage unique"\n'
            '[[personnes]]\nnom = "Sophie"\nrole = "cheffe de projet"\n',
            encoding="utf-8",
        )
        context = read(file)
        assert context.termes[0].ecriture == "OTP"
        assert context.intervenants[0].role == "cheffe de projet"

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path):
        assert read(tmp_path / "jamais-ecrit.toml").empty

    def test_un_fichier_illisible_ne_bloque_pas_la_reunion(self, tmp_path):
        """Mieux vaut démarrer sans glossaire que refuser de démarrer."""
        file = tmp_path / "contexte.toml"
        file.write_text("[[termes]\nceci n'est pas du TOML", encoding="utf-8")
        assert read(file).empty

    def test_une_entree_sans_ecriture_est_ecartee_sans_tout_perdre(self, tmp_path):
        file = tmp_path / "contexte.toml"
        file.write_text(
            '[[termes]]\nsens = "orpheline"\n[[termes]]\necriture = "CASA"\n',
            encoding="utf-8",
        )
        context = read(file)
        assert [t.ecriture for t in context.termes] == ["CASA"]


class TestSourcesDeja:
    """Deux sources existaient déjà et n'étaient pas exploitées."""

    def test_le_vocabulaire_de_la_configuration_est_reprise(self):
        context = from_vocabulary(["CASA", "OTP", "  "])
        assert [t.ecriture for t in context.termes] == ["CASA", "OTP"]

    def test_la_banque_de_voix_fournit_les_habitues(self):
        """Un prénom mal transcrit décide de l'attribution des tours de parole."""
        context = from_the_bank(["Katell", "Pascal", ""])
        assert [i.name for i in context.intervenants] == ["Katell", "Pascal"]


class TestGabarit:
    def test_le_gabarit_est_pose_une_seule_fois(self, tmp_path):
        file = tmp_path / "contexte.toml"
        assert lay_the_template(file) is True
        assert lay_the_template(file) is False

    def test_le_gabarit_pose_est_lisible_et_utile(self, tmp_path):
        file = tmp_path / "contexte.toml"
        lay_the_template(file)
        context = read(file)
        assert not context.empty, "un gabarit sans exemple actif n'apprend rien"


class TestAjoutDepuisLaConversation:
    """Alimenter le contexte demandait d'ouvrir un fichier."""

    def test_un_terme_s_ajoute_avec_son_sens(self, tmp_path):
        from greffier.adapters.context_file import add_a_term

        file = tmp_path / "contexte.toml"
        assert add_a_term(file, "OTP", "mot de passe à usage unique")
        term = next(t for t in read(file).termes if t.ecriture == "OTP")
        assert term.sens == "mot de passe à usage unique"

    def test_une_personne_s_ajoute_avec_son_role(self, tmp_path):
        from greffier.adapters.context_file import add_a_person

        file = tmp_path / "contexte.toml"
        assert add_a_person(file, "Maud", "cheffe de projet")
        gens = read(file).intervenants
        assert gens[-1].name == "Maud"
        assert gens[-1].role == "cheffe de projet"

    def test_une_personne_deja_connue_n_est_pas_doublee(self, tmp_path):
        from greffier.adapters.context_file import add_a_person

        file = tmp_path / "contexte.toml"
        add_a_person(file, "Maud", "cheffe de projet")
        assert add_a_person(file, "maud") is False

    def test_les_commentaires_survivent_aux_ajouts(self, tmp_path):
        """Le fichier est édité à la main : on ajoute au bout, on ne régénère pas."""
        from greffier.adapters.context_file import (
            add_a_person,
            lay_the_template,
        )

        file = tmp_path / "contexte.toml"
        lay_the_template(file)
        add_a_person(file, "Maud", "cheffe de projet")
        assert "il faut les lui dire" in file.read_text(encoding="utf-8")

    def test_un_nom_vide_est_refuse(self, tmp_path):
        from greffier.adapters.context_file import add_a_person

        assert add_a_person(tmp_path / "contexte.toml", "  ") is False
