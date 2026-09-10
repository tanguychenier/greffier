"""Les documents fournis pour une réunion, gardés sous forme de texte."""

from pathlib import Path

import pytest

from greffier.adapters import attachments_file


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path / "pieces"


class TestGarder:
    def test_le_texte_est_garde_sous_la_reunion(self, base):
        piece = attachments_file.write(base, "reunion-1", "Ordre du jour.pdf", "Point sur CASA")
        assert piece is not None
        assert piece.file.parent.name == "reunion-1"
        assert "Point sur CASA" in piece.file.read_text(encoding="utf-8")

    def test_le_nom_d_origine_survit_a_l_aplatissement(self, base):
        """« cahier des charges V3.pdf » est ce qu'il faut montrer à l'écran."""
        attachments_file.write(base, "r", "Cahier des charges V3.pdf", "du texte")
        assert attachments_file.lister(base, "r")[0].name == "Cahier des charges V3.pdf"

    def test_un_nom_accentue_donne_un_fichier_sur(self, base):
        piece = attachments_file.write(base, "r", "Réunion été 2026.docx", "du texte")
        assert piece is not None
        assert piece.file.name == "reunion-ete-2026-docx.txt"

    def test_un_document_vide_n_est_pas_garde(self, base):
        assert attachments_file.write(base, "r", "vide.txt", "   \n ") is None

    def test_sans_reunion_rien_n_est_range(self, base):
        """Ranger un texte sous une réunion au hasard rendrait le dossier trompeur."""
        assert attachments_file.write(base, "", "x.txt", "du texte") is None

    def test_redeposer_le_meme_document_remplace_l_ancien(self, base):
        """On redépose un document parce qu'il a changé."""
        attachments_file.write(base, "r", "note.txt", "version une")
        attachments_file.write(base, "r", "note.txt", "version deux")
        pieces = attachments_file.lister(base, "r")
        assert len(pieces) == 1
        assert "version deux" in pieces[0].file.read_text(encoding="utf-8")
        assert "version une" not in pieces[0].file.read_text(encoding="utf-8")


class TestLister:
    def test_une_reunion_sans_document_ne_rend_rien(self, base):
        assert attachments_file.lister(base, "r") == []

    def test_le_poids_est_dit_sans_le_calculer_a_l_ecran(self, base):
        attachments_file.write(base, "r", "gros.txt", "x" * 4200)
        assert "4 k" in attachments_file.lister(base, "r")[0].say()

    def test_un_document_court_ne_se_dit_pas_zero(self, base):
        attachments_file.write(base, "r", "court.txt", "deux mots")
        assert "1 k" in attachments_file.lister(base, "r")[0].say()


class TestMatiere:
    def test_chaque_document_est_annonce_par_son_nom(self, base):
        """Sans le nom, deux documents contradictoires deviennent une seule voix."""
        attachments_file.write(base, "r", "Ordre du jour.pdf", "on parlera de CASA")
        attachments_file.write(base, "r", "Note.txt", "CASA est reporté")
        rendered = attachments_file.material(base, "r")
        assert "Ordre du jour.pdf" in rendered and "Note.txt" in rendered
        assert "on parlera de CASA" in rendered and "CASA est reporté" in rendered

    def test_l_entete_du_fichier_ne_se_retrouve_pas_dans_la_matiere(self, base):
        attachments_file.write(base, "r", "Note.txt", "le corps")
        assert "# Note.txt" not in attachments_file.material(base, "r")

    def test_un_document_enorme_est_tronque(self, base):
        attachments_file.write(base, "r", "pave.txt", "x" * 50_000)
        rendered = attachments_file.material(base, "r")
        assert "tronqué" in rendered
        assert len(rendered) < attachments_file.AT_MOST + 200

    def test_un_pave_ne_chasse_pas_les_autres_documents(self, base):
        """Sans borne par document, les trois autres n'apparaissaient pas du tout."""
        attachments_file.write(base, "r", "pave.txt", "x" * 40_000)
        attachments_file.write(base, "r", "bref.txt", "la décision")
        assert "la décision" in attachments_file.material(base, "r")

    def test_la_matiere_est_vide_sans_document(self, base):
        assert attachments_file.material(base, "r") == ""
