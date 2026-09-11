"""Le registre des sujets : ce qui ne se devine pas s'écrit une fois."""

from greffier.adapters.subjects_file import lay_the_template, noter_la_carte, read


class TestReadingTheSetting:
    def test_a_subject_and_its_aliases_are_read(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text(
            '[[sujets]]\nnom = "Oasis"\nalias = ["esup-oasis"]\ncarte = "uXjV1="\n',
            encoding="utf-8",
        )
        subject = read(file).by_name("esup-oasis")
        assert subject is not None
        assert subject.name == "Oasis" and subject.board == "uXjV1="

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert read(tmp_path / "jamais.toml").subjects == []

    def test_a_broken_file_does_not_block_the_meeting(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text("[[sujets]\npas du TOML", encoding="utf-8")
        assert read(file).subjects == []

    def test_an_entry_with_no_name_is_dropped(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text('[[sujets]]\ncarte = "uXjV1="\n', encoding="utf-8")
        assert read(file).subjects == []


class TestAjoutSeul:
    """Le fichier porte des commentaires : on ne le régénère jamais."""

    def test_the_board_of_a_new_subject_is_noted(self, tmp_path):
        file = tmp_path / "sujets.toml"
        assert noter_la_carte(file, "Oasis", "uXjV1=") is True
        subject = read(file).by_name("Oasis")
        assert subject is not None and subject.board == "uXjV1="

    def test_a_subject_already_mapped_is_untouched(self, tmp_path):
        """Deux cartes pour un sujet est ce qu'on cherche à éviter."""
        file = tmp_path / "sujets.toml"
        noter_la_carte(file, "Oasis", "premiere=")
        assert noter_la_carte(file, "Oasis", "seconde=") is False
        subject = read(file).by_name("Oasis")
        assert subject is not None and subject.board == "premiere="

    def test_a_listed_subject_with_no_board_gets_its_own(self, tmp_path):
        file = tmp_path / "sujets.toml"
        file.write_text(
            '[[sujets]]\nnom = "Oasis"\nalias = ["esup-oasis"]\n', encoding="utf-8"
        )
        assert noter_la_carte(file, "Oasis", "uXjV1=") is True
        subject = read(file).by_name("Oasis")
        assert subject is not None
        assert subject.board == "uXjV1=", "la dernière entrée l'emporte"
        assert "esup-oasis" in subject.alias, "les alias survivent"

    def test_the_comments_of_the_template_survive(self, tmp_path):
        file = tmp_path / "sujets.toml"
        lay_the_template(file)
        noter_la_carte(file, "Oasis", "uXjV1=")
        assert "ne se devine pas" in file.read_text(encoding="utf-8")
