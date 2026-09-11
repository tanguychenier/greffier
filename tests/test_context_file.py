"""Lire le contexte du milieu, et le compléter depuis ce qu'on sait déjà."""

from greffier.adapters.context_file import (
    from_the_bank,
    from_vocabulary,
    lay_the_template,
    read,
)


class TestReadingTheContextFile:
    def test_terms_and_people_are_read(self, tmp_path):
        file = tmp_path / "contexte.toml"
        file.write_text(
            '[[termes]]\necriture = "OTP"\nsens = "mot de passe à usage unique"\n'
            '[[personnes]]\nnom = "Sophie"\nrole = "cheffe de projet"\n',
            encoding="utf-8",
        )
        context = read(file)
        assert context.termes[0].ecriture == "OTP"
        assert context.intervenants[0].role == "cheffe de projet"

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert read(tmp_path / "jamais-ecrit.toml").empty

    def test_an_unreadable_file_does_not_block_the_meeting(self, tmp_path):
        """Mieux vaut démarrer sans glossaire que refuser de démarrer."""
        file = tmp_path / "contexte.toml"
        file.write_text("[[termes]\nceci n'est pas du TOML", encoding="utf-8")
        assert read(file).empty

    def test_an_entry_with_no_spelling_is_dropped_without_losing_the_rest(self, tmp_path):
        file = tmp_path / "contexte.toml"
        file.write_text(
            '[[termes]]\nsens = "orpheline"\n[[termes]]\necriture = "CASA"\n',
            encoding="utf-8",
        )
        context = read(file)
        assert [t.ecriture for t in context.termes] == ["CASA"]


class TestSourcesDeja:
    """Deux sources existaient déjà et n'étaient pas exploitées."""

    def test_the_vocabulary_from_the_settings_is_taken_in(self):
        context = from_vocabulary(["CASA", "OTP", "  "])
        assert [t.ecriture for t in context.termes] == ["CASA", "OTP"]

    def test_the_voice_bank_supplies_the_regulars(self):
        """Un prénom mal transcrit décide de l'attribution des tours de parole."""
        context = from_the_bank(["Katell", "Pascal", ""])
        assert [i.name for i in context.intervenants] == ["Katell", "Pascal"]


class TestTheTemplateFile:
    def test_the_template_is_laid_down_once(self, tmp_path):
        file = tmp_path / "contexte.toml"
        assert lay_the_template(file) is True
        assert lay_the_template(file) is False

    def test_the_template_laid_down_is_readable_and_useful(self, tmp_path):
        file = tmp_path / "contexte.toml"
        lay_the_template(file)
        context = read(file)
        assert not context.empty, "un gabarit sans exemple actif n'apprend rien"


class TestAddingFromTheConversation:
    """Alimenter le contexte demandait d'ouvrir un fichier."""

    def test_a_term_is_added_with_its_meaning(self, tmp_path):
        from greffier.adapters.context_file import add_a_term

        file = tmp_path / "contexte.toml"
        assert add_a_term(file, "OTP", "mot de passe à usage unique")
        term = next(t for t in read(file).termes if t.ecriture == "OTP")
        assert term.sens == "mot de passe à usage unique"

    def test_a_person_is_added_with_their_role(self, tmp_path):
        from greffier.adapters.context_file import add_a_person

        file = tmp_path / "contexte.toml"
        assert add_a_person(file, "Maud", "cheffe de projet")
        gens = read(file).intervenants
        assert gens[-1].name == "Maud"
        assert gens[-1].role == "cheffe de projet"

    def test_a_person_already_known_is_not_doubled(self, tmp_path):
        from greffier.adapters.context_file import add_a_person

        file = tmp_path / "contexte.toml"
        add_a_person(file, "Maud", "cheffe de projet")
        assert add_a_person(file, "maud") is False

    def test_the_comments_survive_the_additions(self, tmp_path):
        """Le fichier est édité à la main : on ajoute au bout, on ne régénère pas."""
        from greffier.adapters.context_file import (
            add_a_person,
            lay_the_template,
        )

        file = tmp_path / "contexte.toml"
        lay_the_template(file)
        add_a_person(file, "Maud", "cheffe de projet")
        assert "il faut les lui dire" in file.read_text(encoding="utf-8")

    def test_an_empty_name_is_refused(self, tmp_path):
        from greffier.adapters.context_file import add_a_person

        assert add_a_person(tmp_path / "contexte.toml", "  ") is False
