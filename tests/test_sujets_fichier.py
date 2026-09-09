"""Le registre des sujets : ce qui ne se devine pas s'écrit une fois."""

from greffier.adaptateurs.sujets_fichier import lire, noter_la_carte, poser_le_gabarit


class TestLecture:
    def test_un_sujet_et_ses_alias_sont_lus(self, tmp_path):
        fichier = tmp_path / "sujets.toml"
        fichier.write_text(
            '[[sujets]]\nnom = "Oasis"\nalias = ["esup-oasis"]\ncarte = "uXjV1="\n',
            encoding="utf-8",
        )
        sujet = lire(fichier).par_nom("esup-oasis")
        assert sujet is not None
        assert sujet.nom == "Oasis" and sujet.carte == "uXjV1="

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path):
        assert lire(tmp_path / "jamais.toml").sujets == []

    def test_un_fichier_casse_ne_bloque_pas_la_reunion(self, tmp_path):
        fichier = tmp_path / "sujets.toml"
        fichier.write_text("[[sujets]\npas du TOML", encoding="utf-8")
        assert lire(fichier).sujets == []

    def test_une_entree_sans_nom_est_ecartee(self, tmp_path):
        fichier = tmp_path / "sujets.toml"
        fichier.write_text('[[sujets]]\ncarte = "uXjV1="\n', encoding="utf-8")
        assert lire(fichier).sujets == []


class TestAjoutSeul:
    """Le fichier porte des commentaires : on ne le régénère jamais."""

    def test_la_carte_d_un_sujet_neuf_est_notee(self, tmp_path):
        fichier = tmp_path / "sujets.toml"
        assert noter_la_carte(fichier, "Oasis", "uXjV1=") is True
        sujet = lire(fichier).par_nom("Oasis")
        assert sujet is not None and sujet.carte == "uXjV1="

    def test_un_sujet_deja_carte_n_est_pas_touche(self, tmp_path):
        """Deux cartes pour un sujet est ce qu'on cherche à éviter."""
        fichier = tmp_path / "sujets.toml"
        noter_la_carte(fichier, "Oasis", "premiere=")
        assert noter_la_carte(fichier, "Oasis", "seconde=") is False
        sujet = lire(fichier).par_nom("Oasis")
        assert sujet is not None and sujet.carte == "premiere="

    def test_un_sujet_liste_sans_carte_recoit_la_sienne(self, tmp_path):
        fichier = tmp_path / "sujets.toml"
        fichier.write_text(
            '[[sujets]]\nnom = "Oasis"\nalias = ["esup-oasis"]\n', encoding="utf-8"
        )
        assert noter_la_carte(fichier, "Oasis", "uXjV1=") is True
        sujet = lire(fichier).par_nom("Oasis")
        assert sujet is not None
        assert sujet.carte == "uXjV1=", "la dernière entrée l'emporte"
        assert "esup-oasis" in sujet.alias, "les alias survivent"

    def test_les_commentaires_du_gabarit_survivent(self, tmp_path):
        fichier = tmp_path / "sujets.toml"
        poser_le_gabarit(fichier)
        noter_la_carte(fichier, "Oasis", "uXjV1=")
        assert "ne se devine pas" in fichier.read_text(encoding="utf-8")
