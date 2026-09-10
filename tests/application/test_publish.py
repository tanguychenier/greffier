"""Exécuter un dépôt : extraire le son, tirer du contexte d'un document."""


from greffier.application.publish import (
    CONSIGNES_DOCUMENT,
    LU_AU_PLUS,
    learn_from_document,
    lire_le_texte,
    run_chain,
    tools_present,
)
from greffier.domain.store import Destination, Suggestion


class FakeWriter:
    def __init__(self, rendered: str) -> None:
        self.rendered = rendered
        self.recu = ""

    def write_up(self, text: str) -> str:
        self.recu = text
        return self.rendered


class TestLectureDesDocuments:
    def test_un_texte_brut_se_lit(self, tmp_path):
        file = tmp_path / "note.md"
        file.write_text("Le circuit FAST remplace le papier.", encoding="utf-8")
        assert "FAST" in lire_le_texte(file)

    def test_un_format_inconnu_ne_leve_pas(self, tmp_path):
        file = tmp_path / "x.zip"
        file.write_bytes(b"PK\\x03\\x04")
        assert lire_le_texte(file) == ""

    def test_un_fichier_absent_ne_leve_pas(self, tmp_path):
        assert lire_le_texte(tmp_path / "jamais.md") == ""


class TestApprentissageDepuisUnDocument:
    """Le document n'est pas versé tel quel : on en tire du vocabulaire.

    Un compte rendu de dix pages dans l'amorce du transcripteur la ferait
    tronquer sans prévenir.
    """

    def test_les_entrees_sont_lues(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("FAST et CASA.", encoding="utf-8")
        writer = FakeWriter(
            '[{"ecriture": "FAST", "sens": "un circuit", "genre": "terme"},'
            ' {"ecriture": "Maud", "sens": "pilote", "genre": "personne"}]'
        )
        appris = learn_from_document(file, writer)
        assert ("FAST", "un circuit", "terme") in appris
        assert ("Maud", "pilote", "personne") in appris

    def test_un_document_vide_n_appelle_pas_le_redacteur(self, tmp_path):
        file = tmp_path / "vide.md"
        file.write_text("   ", encoding="utf-8")
        writer = FakeWriter("[]")
        assert learn_from_document(file, writer) == ()
        assert writer.recu == ""

    def test_une_reponse_illisible_ne_rend_rien(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("du texte", encoding="utf-8")
        assert learn_from_document(file, FakeWriter("je ne sais pas")) == ()

    def test_un_bloc_de_code_est_accepte(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("du texte", encoding="utf-8")
        appris = learn_from_document(
            file, FakeWriter('```json\\n[{"ecriture": "FAST"}]\\n```')
        )
        assert appris == (("FAST", "", "terme"),)

    def test_seul_le_debut_du_document_est_lu(self, tmp_path):
        """Cent pages ne se lisent pas pour en tirer vingt mots."""
        file = tmp_path / "gros.md"
        file.write_text("x" * (LU_AU_PLUS * 2), encoding="utf-8")
        writer = FakeWriter("[]")
        learn_from_document(file, writer)
        assert len(writer.recu) <= len(CONSIGNES_DOCUMENT) + LU_AU_PLUS

    def test_les_consignes_excluent_les_mots_courants(self):
        aplati = " ".join(CONSIGNES_DOCUMENT.split())
        assert "Pas les mots courants" in aplati
        assert "n'invente pas" in aplati


class TestExecution:
    def test_un_son_est_copie_la_ou_la_chaine_travaille(self, tmp_path):
        """Un fichier déposé depuis une clé USB ne doit pas rester la seule copie."""
        source = tmp_path / "ailleurs" / "reunion.wav"
        source.parent.mkdir()
        source.write_bytes(b"x" * 300_000)
        proposition = Suggestion(source, Destination.MEETING, "enregistrement sonore")
        done = run_chain(proposition, tmp_path / "enregistrements")
        assert done.produit is not None and done.produit.exists()
        assert done.trouble == ""

    def test_un_fichier_bloque_est_rapporte_et_non_tente(self, tmp_path):
        proposition = Suggestion(
            tmp_path / "x.mp4", Destination.VIDEO, "vidéo",
            blocked_by="ffmpeg est introuvable",
        )
        done = run_chain(proposition, tmp_path / "enregistrements")
        assert "ffmpeg" in done.trouble

    def test_un_document_sans_redacteur_le_dit(self, tmp_path):
        file = tmp_path / "note.md"
        file.write_text("du texte", encoding="utf-8")
        done = run_chain(
            Suggestion(file, Destination.CONTEXT, "texte"),
            tmp_path / "enregistrements", writer=None,
        )
        assert "aucun rédacteur" in done.trouble


class TestOutils:
    def test_les_outils_presents_sont_ceux_du_poste(self):
        found = tools_present()
        assert isinstance(found, frozenset)
        assert found <= {"ffmpeg", "pdftotext", "textutil"}
