"""Classer un fichier déposé : ce qu'il est, et ce qu'on peut en faire.

Traiter tout de la même façon produirait un fourre-tout qui n'organise rien.
Une vidéo de deux heures mal classée coûte une transcription pour rien ; un
document classé en réunion produit un compte rendu d'un texte que personne n'a
prononcé.
"""

from pathlib import Path

from greffier.domain.store import (
    MINIMUM_SOUND_SIZE,
    Destination,
    offer,
    summarise,
)

TOUS = frozenset({"ffmpeg", "pdftotext", "textutil"})


class TestSons:
    def test_un_enregistrement_devient_une_reunion(self):
        propose = offer(Path("reunion.wav"), 50_000_000, TOUS)
        assert propose.destination is Destination.MEETING
        assert propose.feasible

    def test_les_formats_courants_sont_reconnus(self):
        for suffixe in (".wav", ".m4a", ".mp3", ".opus", ".flac"):
            assert offer(
                Path(f"x{suffixe}"), 50_000_000, TOUS
            ).destination is Destination.MEETING

    def test_un_son_trop_court_n_est_pas_une_reunion(self):
        """Une notification système, un bip, un extrait."""
        propose = offer(Path("bip.wav"), MINIMUM_SOUND_SIZE - 1, TOUS)
        assert propose.destination is Destination.UNKNOWN
        assert "trop court" in propose.because

    def test_le_seuil_reste_bas(self):
        """Une réunion d'une minute pèse déjà 2 Mo en WAV."""
        assert 50_000 <= MINIMUM_SOUND_SIZE <= 2_000_000


class TestVideos:
    def test_un_enregistrement_teams_est_reconnu(self):
        propose = offer(Path("Teams-2026-09-09.mp4"), 800_000_000, TOUS)
        assert propose.destination is Destination.VIDEO
        assert propose.feasible

    def test_ce_qui_manque_est_dit_plutot_que_le_fichier_ecarte(self):
        """Dire « il faudrait ffmpeg » est plus utile que faire disparaître."""
        propose = offer(Path("x.mp4"), 10_000_000, frozenset())
        assert propose.destination is Destination.VIDEO
        assert not propose.feasible
        assert "ffmpeg" in propose.blocked_by


class TestDocuments:
    def test_un_texte_se_lit_sans_rien_installer(self):
        propose = offer(Path("compte-rendu.md"), 4_000, frozenset())
        assert propose.destination is Destination.CONTEXT
        assert propose.feasible, "aucun outil n'est requis"

    def test_un_pdf_demande_un_outil(self):
        assert offer(Path("x.pdf"), 2_000_000, frozenset()).blocked_by
        assert offer(Path("x.pdf"), 2_000_000, TOUS).feasible

    def test_un_document_bureautique_demande_textutil(self):
        propose = offer(Path("x.docx"), 40_000, frozenset())
        assert "textutil" in propose.blocked_by


class TestCeQuOnNeSaitPasClasser:
    def test_un_export_de_donnees_est_dit_inconnu(self):
        propose = offer(Path("export.csv"), 10_000, TOUS)
        assert propose.destination is Destination.UNKNOWN
        assert ".csv" in propose.because

    def test_un_fichier_sans_extension(self):
        propose = offer(Path("machin"), 1_000, TOUS)
        assert propose.destination is Destination.UNKNOWN
        assert "sans extension" in propose.because

    def test_l_inconnu_n_est_jamais_faisable(self):
        assert not offer(Path("x.zip"), 1_000, TOUS).feasible


class TestResume:
    def test_il_dit_ce_que_le_lot_va_devenir(self):
        propositions = [
            offer(Path("a.wav"), 50_000_000, TOUS),
            offer(Path("b.mp4"), 50_000_000, TOUS),
            offer(Path("c.md"), 4_000, TOUS),
        ]
        sentence = summarise(propositions)
        assert "réunion" in sentence and "vidéo" in sentence and "contexte" in sentence

    def test_il_signale_ce_qui_attend_un_outil(self):
        sentence = summarise([offer(Path("a.mp4"), 50_000_000, frozenset())])
        assert "attente d'un outil" in sentence

    def test_un_lot_vide_le_dit(self):
        assert summarise([]) == "Aucun fichier."
