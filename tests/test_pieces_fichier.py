"""Les documents fournis pour une réunion, gardés sous forme de texte."""

from pathlib import Path

import pytest

from greffier.adaptateurs import pieces_fichier


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path / "pieces"


class TestGarder:
    def test_le_texte_est_garde_sous_la_reunion(self, base):
        piece = pieces_fichier.ecrire(base, "reunion-1", "Ordre du jour.pdf", "Point sur CASA")
        assert piece is not None
        assert piece.fichier.parent.name == "reunion-1"
        assert "Point sur CASA" in piece.fichier.read_text(encoding="utf-8")

    def test_le_nom_d_origine_survit_a_l_aplatissement(self, base):
        """« cahier des charges V3.pdf » est ce qu'il faut montrer à l'écran."""
        pieces_fichier.ecrire(base, "r", "Cahier des charges V3.pdf", "du texte")
        assert pieces_fichier.lister(base, "r")[0].nom == "Cahier des charges V3.pdf"

    def test_un_nom_accentue_donne_un_fichier_sur(self, base):
        piece = pieces_fichier.ecrire(base, "r", "Réunion été 2026.docx", "du texte")
        assert piece is not None
        assert piece.fichier.name == "reunion-ete-2026-docx.txt"

    def test_un_document_vide_n_est_pas_garde(self, base):
        assert pieces_fichier.ecrire(base, "r", "vide.txt", "   \n ") is None

    def test_sans_reunion_rien_n_est_range(self, base):
        """Ranger un texte sous une réunion au hasard rendrait le dossier trompeur."""
        assert pieces_fichier.ecrire(base, "", "x.txt", "du texte") is None

    def test_redeposer_le_meme_document_remplace_l_ancien(self, base):
        """On redépose un document parce qu'il a changé."""
        pieces_fichier.ecrire(base, "r", "note.txt", "version une")
        pieces_fichier.ecrire(base, "r", "note.txt", "version deux")
        pieces = pieces_fichier.lister(base, "r")
        assert len(pieces) == 1
        assert "version deux" in pieces[0].fichier.read_text(encoding="utf-8")
        assert "version une" not in pieces[0].fichier.read_text(encoding="utf-8")


class TestLister:
    def test_une_reunion_sans_document_ne_rend_rien(self, base):
        assert pieces_fichier.lister(base, "r") == []

    def test_le_poids_est_dit_sans_le_calculer_a_l_ecran(self, base):
        pieces_fichier.ecrire(base, "r", "gros.txt", "x" * 4200)
        assert "4 k" in pieces_fichier.lister(base, "r")[0].dire()

    def test_un_document_court_ne_se_dit_pas_zero(self, base):
        pieces_fichier.ecrire(base, "r", "court.txt", "deux mots")
        assert "1 k" in pieces_fichier.lister(base, "r")[0].dire()


class TestMatiere:
    def test_chaque_document_est_annonce_par_son_nom(self, base):
        """Sans le nom, deux documents contradictoires deviennent une seule voix."""
        pieces_fichier.ecrire(base, "r", "Ordre du jour.pdf", "on parlera de CASA")
        pieces_fichier.ecrire(base, "r", "Note.txt", "CASA est reporté")
        rendu = pieces_fichier.matiere(base, "r")
        assert "Ordre du jour.pdf" in rendu and "Note.txt" in rendu
        assert "on parlera de CASA" in rendu and "CASA est reporté" in rendu

    def test_l_entete_du_fichier_ne_se_retrouve_pas_dans_la_matiere(self, base):
        pieces_fichier.ecrire(base, "r", "Note.txt", "le corps")
        assert "# Note.txt" not in pieces_fichier.matiere(base, "r")

    def test_un_document_enorme_est_tronque(self, base):
        pieces_fichier.ecrire(base, "r", "pave.txt", "x" * 50_000)
        rendu = pieces_fichier.matiere(base, "r")
        assert "tronqué" in rendu
        assert len(rendu) < pieces_fichier.AU_PLUS + 200

    def test_un_pave_ne_chasse_pas_les_autres_documents(self, base):
        """Sans borne par document, les trois autres n'apparaissaient pas du tout."""
        pieces_fichier.ecrire(base, "r", "pave.txt", "x" * 40_000)
        pieces_fichier.ecrire(base, "r", "bref.txt", "la décision")
        assert "la décision" in pieces_fichier.matiere(base, "r")

    def test_la_matiere_est_vide_sans_document(self, base):
        assert pieces_fichier.matiere(base, "r") == ""
