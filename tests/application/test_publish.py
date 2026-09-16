"""Running a drop: pulling the sound out, drawing context from a document."""

import shutil
import subprocess

import pytest

from greffier.application.publish import (
    DOCUMENT_GUIDANCE,
    READ_AT_MOST,
    extract_sound,
    learn_from_document,
    read_the_text,
    run_chain,
    tools_present,
)
from greffier.domain.store import Destination, Suggestion


class FakeWriter:
    def __init__(self, rendered: str) -> None:
        self.rendered = rendered
        self.received = ""

    def write_up(self, text: str) -> str:
        self.received = text
        return self.rendered


class TestReadingTheDocuments:
    def test_a_plain_text_reads(self, tmp_path):
        file = tmp_path / "note.md"
        file.write_text("Le circuit FAST remplace le papier.", encoding="utf-8")
        assert "FAST" in read_the_text(file)

    def test_an_unknown_format_does_not_raise(self, tmp_path):
        file = tmp_path / "x.zip"
        file.write_bytes(b"PK\\x03\\x04")
        assert read_the_text(file) == ""

    def test_a_missing_file_does_not_raise(self, tmp_path):
        assert read_the_text(tmp_path / "jamais.md") == ""


class TestLearningFromADocument:
    """The document is not poured in as it is: vocabulary is drawn from it.

    Ten pages of minutes in the transcriber's prompt would have it truncated
    without warning.
    """

    def test_the_entries_are_read(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("FAST et CASA.", encoding="utf-8")
        writer = FakeWriter(
            '[{"ecriture": "FAST", "sens": "un circuit", "genre": "terme"},'
            ' {"ecriture": "Maud", "sens": "pilote", "genre": "personne"}]'
        )
        learned = learn_from_document(file, writer)
        assert ("FAST", "un circuit", "terme") in learned
        assert ("Maud", "pilote", "personne") in learned

    def test_an_empty_document_does_not_call_the_writer(self, tmp_path):
        file = tmp_path / "vide.md"
        file.write_text("   ", encoding="utf-8")
        writer = FakeWriter("[]")
        assert learn_from_document(file, writer) == ()
        assert writer.received == ""

    def test_an_unreadable_answer_returns_nothing(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("du texte", encoding="utf-8")
        assert learn_from_document(file, FakeWriter("je ne sais pas")) == ()

    def test_a_code_fence_is_accepted(self, tmp_path):
        file = tmp_path / "specs.md"
        file.write_text("du texte", encoding="utf-8")
        learned = learn_from_document(
            file, FakeWriter('```json\\n[{"ecriture": "FAST"}]\\n```')
        )
        assert learned == (("FAST", "", "terme"),)

    def test_only_the_start_of_the_document_is_read(self, tmp_path):
        """A hundred pages are not read to draw twenty words from them."""
        file = tmp_path / "gros.md"
        file.write_text("x" * (READ_AT_MOST * 2), encoding="utf-8")
        writer = FakeWriter("[]")
        learn_from_document(file, writer)
        assert len(writer.received) <= len(DOCUMENT_GUIDANCE) + READ_AT_MOST

    def test_the_guidance_rules_out_everyday_words(self):
        flattened = " ".join(DOCUMENT_GUIDANCE.split())
        assert "Pas les mots courants" in flattened
        assert "n'invente pas" in flattened


class TestFilingTheFiles:
    def test_a_sound_is_copied_where_the_chain_works(self, tmp_path):
        """A file handed over from a USB stick must not remain the only copy."""
        source = tmp_path / "ailleurs" / "reunion.wav"
        source.parent.mkdir()
        source.write_bytes(b"x" * 300_000)
        proposition = Suggestion(source, Destination.MEETING, "enregistrement sonore")
        done = run_chain(proposition, tmp_path / "enregistrements")
        assert done.product is not None and done.product.exists()
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


class TestPullingTheSoundOutOfAVideo:
    """A two-hour video is a meeting once its sound is out; ffmpeg does it."""

    @pytest.fixture
    def video(self, tmp_path):
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg absent")
        target = tmp_path / "reunion.mp4"
        done = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=1",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(target)],
            capture_output=True, text=True, check=False,
        )
        if done.returncode != 0:
            pytest.skip(f"ffmpeg cannot make a video here: {done.stderr[-120:]}")
        return target

    def test_the_sound_track_comes_out_as_the_chain_wants_it(self, video, tmp_path):
        import soundfile as sf

        sound = extract_sound(video, tmp_path / "enregistrements" / "reunion.wav")
        info = sf.info(str(sound))
        assert info.channels == 1 and info.samplerate == 16000
        assert 0.8 < info.duration < 1.3

    def test_a_video_run_through_the_chain_becomes_a_recording(self, video, tmp_path):
        done = run_chain(Suggestion(video, Destination.VIDEO, "vidéo"),
                         tmp_path / "enregistrements")
        assert done.trouble == ""
        assert done.product == tmp_path / "enregistrements" / "reunion.wav"

    def test_something_that_is_not_a_video_says_so(self, tmp_path):
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg absent")
        fake = tmp_path / "x.mp4"
        fake.write_bytes(b"not a video")
        with pytest.raises(RuntimeError, match="extraction du son impossible"):
            extract_sound(fake, tmp_path / "x.wav")


class TestReadingThroughATool:
    def test_a_pdf_is_read_through_pdftotext_when_it_is_there(self, tmp_path, monkeypatch):
        from greffier.application import publish

        monkeypatch.setattr(publish.shutil, "which", lambda name: "/usr/bin/pdftotext")

        class Done:
            returncode = 0
            stdout = "Budget du lot 2 : 42 000 euros."

        monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: Done())
        assert read_the_text(tmp_path / "budget.pdf") == "Budget du lot 2 : 42 000 euros."

    def test_a_pdf_without_pdftotext_reads_empty(self, tmp_path, monkeypatch):
        from greffier.application import publish

        monkeypatch.setattr(publish.shutil, "which", lambda name: None)
        assert read_the_text(tmp_path / "budget.pdf") == ""

    def test_a_tool_that_fails_reads_empty(self, tmp_path, monkeypatch):
        from greffier.application import publish

        monkeypatch.setattr(publish.shutil, "which", lambda name: "/usr/bin/pdftotext")

        class Failed:
            returncode = 1
            stdout = "garbage"

        monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: Failed())
        assert read_the_text(tmp_path / "budget.pdf") == ""

    def test_a_document_read_through_the_chain_teaches_the_context(self, tmp_path):
        file = tmp_path / "glossaire.md"
        file.write_text("CASA : comité d'architecture.", encoding="utf-8")
        writer = FakeWriter('[{"ecriture": "CASA", "sens": "comité", "genre": "terme"}]')
        done = run_chain(Suggestion(file, Destination.CONTEXT, "texte"),
                         tmp_path / "enregistrements", writer=writer)
        assert done.learned == (("CASA", "comité", "terme"),)
