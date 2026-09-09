"""Classer un fichier déposé : ce qu'il est, et ce qu'on peut en faire.

Traiter tout de la même façon produirait un fourre-tout qui n'organise rien.
Une vidéo de deux heures mal classée coûte une transcription pour rien ; un
document classé en réunion produit un compte rendu d'un texte que personne n'a
prononcé.
"""

from pathlib import Path

from greffier.domaine.depot import (
    TAILLE_MINIMALE_SON,
    Destin,
    proposer,
    resumer,
)

TOUS = frozenset({"ffmpeg", "pdftotext", "textutil"})


class TestSons:
    def test_un_enregistrement_devient_une_reunion(self):
        propose = proposer(Path("reunion.wav"), 50_000_000, TOUS)
        assert propose.destin is Destin.REUNION
        assert propose.faisable

    def test_les_formats_courants_sont_reconnus(self):
        for suffixe in (".wav", ".m4a", ".mp3", ".opus", ".flac"):
            assert proposer(
                Path(f"x{suffixe}"), 50_000_000, TOUS
            ).destin is Destin.REUNION

    def test_un_son_trop_court_n_est_pas_une_reunion(self):
        """Une notification système, un bip, un extrait."""
        propose = proposer(Path("bip.wav"), TAILLE_MINIMALE_SON - 1, TOUS)
        assert propose.destin is Destin.INCONNU
        assert "trop court" in propose.parce_que

    def test_le_seuil_reste_bas(self):
        """Une réunion d'une minute pèse déjà 2 Mo en WAV."""
        assert 50_000 <= TAILLE_MINIMALE_SON <= 2_000_000


class TestVideos:
    def test_un_enregistrement_teams_est_reconnu(self):
        propose = proposer(Path("Teams-2026-09-09.mp4"), 800_000_000, TOUS)
        assert propose.destin is Destin.VIDEO
        assert propose.faisable

    def test_ce_qui_manque_est_dit_plutot_que_le_fichier_ecarte(self):
        """Dire « il faudrait ffmpeg » est plus utile que faire disparaître."""
        propose = proposer(Path("x.mp4"), 10_000_000, frozenset())
        assert propose.destin is Destin.VIDEO
        assert not propose.faisable
        assert "ffmpeg" in propose.bloque_par


class TestDocuments:
    def test_un_texte_se_lit_sans_rien_installer(self):
        propose = proposer(Path("compte-rendu.md"), 4_000, frozenset())
        assert propose.destin is Destin.CONTEXTE
        assert propose.faisable, "aucun outil n'est requis"

    def test_un_pdf_demande_un_outil(self):
        assert proposer(Path("x.pdf"), 2_000_000, frozenset()).bloque_par
        assert proposer(Path("x.pdf"), 2_000_000, TOUS).faisable

    def test_un_document_bureautique_demande_textutil(self):
        propose = proposer(Path("x.docx"), 40_000, frozenset())
        assert "textutil" in propose.bloque_par


class TestCeQuOnNeSaitPasClasser:
    def test_un_export_de_donnees_est_dit_inconnu(self):
        propose = proposer(Path("export.csv"), 10_000, TOUS)
        assert propose.destin is Destin.INCONNU
        assert ".csv" in propose.parce_que

    def test_un_fichier_sans_extension(self):
        propose = proposer(Path("machin"), 1_000, TOUS)
        assert propose.destin is Destin.INCONNU
        assert "sans extension" in propose.parce_que

    def test_l_inconnu_n_est_jamais_faisable(self):
        assert not proposer(Path("x.zip"), 1_000, TOUS).faisable


class TestResume:
    def test_il_dit_ce_que_le_lot_va_devenir(self):
        propositions = [
            proposer(Path("a.wav"), 50_000_000, TOUS),
            proposer(Path("b.mp4"), 50_000_000, TOUS),
            proposer(Path("c.md"), 4_000, TOUS),
        ]
        phrase = resumer(propositions)
        assert "réunion" in phrase and "vidéo" in phrase and "contexte" in phrase

    def test_il_signale_ce_qui_attend_un_outil(self):
        phrase = resumer([proposer(Path("a.mp4"), 50_000_000, frozenset())])
        assert "attente d'un outil" in phrase

    def test_un_lot_vide_le_dit(self):
        assert resumer([]) == "Aucun fichier."
