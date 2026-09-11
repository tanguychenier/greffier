"""Le registre des sujets : ce qui ne se devine pas s'écrit une fois."""

from greffier.adapters.subjects_file import lay_the_template, noter_la_carte, read


class TestReadingTheSetting:
    def test_un_sujet_et_ses_alias_sont_lus(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text(
            '[[sujets]]\nnom = "Oasis"\nalias = ["esup-oasis"]\ncarte = "uXjV1="\n',
            encoding="utf-8",
        )
        subject = read(file).by_name("esup-oasis")
        assert subject is not None
        assert subject.name == "Oasis" and subject.board == "uXjV1="

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path):
        assert read(tmp_path / "jamais.toml").subjects == []

    def test_un_fichier_casse_ne_bloque_pas_la_reunion(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text("[[sujets]\npas du TOML", encoding="utf-8")
        assert read(file).subjects == []

    def test_une_entree_sans_nom_est_ecartee(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text('[[sujets]]\ncarte = "uXjV1="\n', encoding="utf-8")
        assert read(file).subjects == []


class TestAjoutSeul:
    """Le fichier porte des commentaires : on ne le régénère jamais."""

    def test_la_carte_d_un_sujet_neuf_est_notee(self, tmp_path):
        file = tmp_path / "sujets.toml"
        assert noter_la_carte(file, "Oasis", "uXjV1=") is True
        subject = read(file).by_name("Oasis")
        assert subject is not None and subject.board == "uXjV1="

    def test_un_sujet_deja_carte_n_est_pas_touche(self, tmp_path):
        """Deux cartes pour un sujet est ce qu'on cherche à éviter."""
        file = tmp_path / "sujets.toml"
        noter_la_carte(file, "Oasis", "premiere=")
        assert noter_la_carte(file, "Oasis", "seconde=") is False
        subject = read(file).by_name("Oasis")
        assert subject is not None and subject.board == "premiere="

    def test_un_sujet_liste_sans_carte_recoit_la_sienne(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text(
            '[[sujets]]\nnom = "Oasis"\nalias = ["esup-oasis"]\n', encoding="utf-8"
        )
        assert noter_la_carte(file, "Oasis", "uXjV1=") is True
        subject = read(file).by_name("Oasis")
        assert subject is not None
        assert subject.board == "uXjV1=", "la dernière entrée l'emporte"
        assert "esup-oasis" in subject.alias, "les alias survivent"

    def test_les_commentaires_du_gabarit_survivent(self, tmp_path):
        file = tmp_path / "sujets.toml"
        lay_the_template(file)
        noter_la_carte(file, "Oasis", "uXjV1=")
        assert "ne se devine pas" in file.read_text(encoding="utf-8")
