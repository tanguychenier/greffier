"""Les documents fournis pour une réunion, gardés sous forme de texte."""

from pathlib import Path

import pytest

from greffier.adapters import attachments_file


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path / "pieces"


class TestGarder:
    def test_the_text_is_kept_under_the_meeting(self, base):
        piece = attachments_file.write(base, "reunion-1", "Ordre du jour.pdf", "Point sur CASA")
        assert piece is not None
        assert piece.file.parent.name == "reunion-1"
        assert "Point sur CASA" in piece.file.read_text(encoding="utf-8")

    def test_the_original_name_survives_the_flattening(self, base):
        """« cahier des charges V3.pdf » est ce qu'il faut montrer à l'écran."""
        attachments_file.write(base, "r", "Cahier des charges V3.pdf", "du texte")
        assert attachments_file.lister(base, "r")[0].name == "Cahier des charges V3.pdf"

    def test_an_accented_name_gives_a_safe_file(self, base):
        piece = attachments_file.write(base, "r", "Réunion été 2026.docx", "du texte")
        assert piece is not None
        assert piece.file.name == "reunion-ete-2026-docx.txt"

    def test_an_empty_document_is_not_kept(self, base):
        assert attachments_file.write(base, "r", "vide.txt", "   \n ") is None

    def test_with_no_meeting_nothing_is_filed(self, base):
        """Ranger un texte sous une réunion au hasard rendrait le dossier trompeur."""
        assert attachments_file.write(base, "", "x.txt", "du texte") is None

    def test_dropping_the_same_document_again_replaces_the_old_one(self, base):
        """On redépose un document parce qu'il a changé."""
        attachments_file.write(base, "r", "note.txt", "version une")
        attachments_file.write(base, "r", "note.txt", "version deux")
        pieces = attachments_file.lister(base, "r")
        assert len(pieces) == 1
        assert "version deux" in pieces[0].file.read_text(encoding="utf-8")
        assert "version une" not in pieces[0].file.read_text(encoding="utf-8")


class TestLister:
    def test_a_meeting_with_no_document_returns_nothing(self, base):
        assert attachments_file.lister(base, "r") == []

    def test_the_weight_is_told_without_computing_it_on_screen(self, base):
        attachments_file.write(base, "r", "gros.txt", "x" * 4200)
        assert "4 k" in attachments_file.lister(base, "r")[0].say()

    def test_a_short_document_is_not_announced_as_zero(self, base):
        attachments_file.write(base, "r", "court.txt", "deux mots")
        assert "1 k" in attachments_file.lister(base, "r")[0].say()


class TestMatiere:
    def test_every_document_is_announced_by_its_name(self, base):
        """Sans le nom, deux documents contradictoires deviennent une seule voix."""
        attachments_file.write(base, "r", "Ordre du jour.pdf", "on parlera de CASA")
        attachments_file.write(base, "r", "Note.txt", "CASA est reporté")
        rendered = attachments_file.material(base, "r")
        assert "Ordre du jour.pdf" in rendered and "Note.txt" in rendered
        assert "on parlera de CASA" in rendered and "CASA est reporté" in rendered

    def test_the_file_header_does_not_end_up_in_the_material(self, base):
        attachments_file.write(base, "r", "Note.txt", "le corps")
        assert "# Note.txt" not in attachments_file.material(base, "r")

    def test_an_enormous_document_is_truncated(self, base):
        attachments_file.write(base, "r", "pave.txt", "x" * 50_000)
        rendered = attachments_file.material(base, "r")
        assert "tronqué" in rendered
        assert len(rendered) < attachments_file.AT_MOST + 200

    def test_one_slab_does_not_crowd_out_the_other_documents(self, base):
        """Sans borne par document, les trois autres n'apparaissaient pas du tout."""
        attachments_file.write(base, "r", "pave.txt", "x" * 40_000)
        attachments_file.write(base, "r", "bref.txt", "la décision")
        assert "la décision" in attachments_file.material(base, "r")

    def test_the_material_is_empty_with_no_document(self, base):
        assert attachments_file.material(base, "r") == ""
