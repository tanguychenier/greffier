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


class TestReadingTheDocuments:
    def test_a_plain_text_reads(self, tmp_path):
        file = tmp_path / "note.md"
        file.write_text("Le circuit FAST remplace le papier.", encoding="utf-8")
        assert "FAST" in lire_le_texte(file)

    def test_an_unknown_format_does_not_raise(self, tmp_path):
        file = tmp_path / "x.zip"
        file.write_bytes(b"PK\\x03\\x04")
        assert lire_le_texte(file) == ""

    def test_a_missing_file_does_not_raise(self, tmp_path):
        assert lire_le_texte(tmp_path / "jamais.md") == ""


class TestLearningFromADocument:
    """Le document n'est pas versé tel quel : on en tire du vocabulaire.

    Un compte rendu de dix pages dans l'amorce du transcripteur la ferait
    tronquer sans prévenir.
    """

    def test_the_entries_are_read(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("FAST et CASA.", encoding="utf-8")
        writer = FakeWriter(
            '[{"ecriture": "FAST", "sens": "un circuit", "genre": "terme"},'
            ' {"ecriture": "Maud", "sens": "pilote", "genre": "personne"}]'
        )
        appris = learn_from_document(file, writer)
        assert ("FAST", "un circuit", "terme") in appris
        assert ("Maud", "pilote", "personne") in appris

    def test_an_empty_document_does_not_call_the_writer(self, tmp_path):
        file = tmp_path / "vide.md"
        file.write_text("   ", encoding="utf-8")
        writer = FakeWriter("[]")
        assert learn_from_document(file, writer) == ()
        assert writer.recu == ""

    def test_an_unreadable_answer_returns_nothing(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("du texte", encoding="utf-8")
        assert learn_from_document(file, FakeWriter("je ne sais pas")) == ()

    def test_a_code_fence_is_accepted(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("du texte", encoding="utf-8")
        appris = learn_from_document(
            file, FakeWriter('```json\\n[{"ecriture": "FAST"}]\\n```')
        )
        assert appris == (("FAST", "", "terme"),)

    def test_only_the_start_of_the_document_is_read(self, tmp_path):
        """Cent pages ne se lisent pas pour en tirer vingt mots."""
        file = tmp_path / "gros.md"
        file.write_text("x" * (LU_AU_PLUS * 2), encoding="utf-8")
        writer = FakeWriter("[]")
        learn_from_document(file, writer)
        assert len(writer.recu) <= len(CONSIGNES_DOCUMENT) + LU_AU_PLUS

    def test_the_guidance_rules_out_everyday_words(self):
        aplati = " ".join(CONSIGNES_DOCUMENT.split())
        assert "Pas les mots courants" in aplati
        assert "n'invente pas" in aplati


class TestFilingTheFiles:
    def test_a_sound_is_copied_where_the_chain_works(self, tmp_path):
        """Un fichier déposé depuis une clé USB ne doit pas rester la seule copie."""
        source = tmp_path / "ailleurs" / "reunion.wav"
        source.parent.mkdir()
        source.write_bytes(b"x" * 300_000)
        proposition = Suggestion(source, Destination.MEETING, "enregistrement sonore")
        done = run_chain(proposition, tmp_path / "enregistrements")
        assert done.produit is not None and done.produit.exists()
        assert done.trouble == ""

    def test_a_blocked_file_is_reported_not_attempted(self, tmp_path):
        proposition = Suggestion(
            tmp_path / "x.mp4", Destination.VIDEO, "vidéo",
            blocked_by="ffmpeg est introuvable",
        )
        done = run_chain(proposition, tmp_path / "enregistrements")
        assert "ffmpeg" in done.trouble

    def test_a_document_with_no_writer_says_so(self, tmp_path):
        file = tmp_path / "note.md"
        file.write_text("du texte", encoding="utf-8")
        done = run_chain(
            Suggestion(file, Destination.CONTEXT, "texte"),
            tmp_path / "enregistrements", writer=None,
        )
        assert "aucun rédacteur" in done.trouble


class TestTheToolsOfThisMachine:
    def test_the_tools_present_are_the_machine_s_own(self):
        found = tools_present()
        assert isinstance(found, frozenset)
        assert found <= {"ffmpeg", "pdftotext", "textutil"}
