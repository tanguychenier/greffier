"""Sorting a file handed over: what it is, and what can be done with it.

Treating everything the same way would produce a catch-all that organises
nothing. A two-hour video sorted wrongly costs a transcription for nothing;
a document sorted as a meeting produces minutes of a text nobody spoke.
"""

from pathlib import Path

from greffier.domain.store import (
    MINIMUM_SOUND_SIZE,
    Destination,
    offer,
    summarise,
)

ALL = frozenset({"ffmpeg", "pdftotext", "textutil"})


class TestSounds:
    def test_a_recording_becomes_a_meeting(self):
        propose = offer(Path("reunion.wav"), 50_000_000, ALL)
        assert propose.destination is Destination.MEETING
        assert propose.feasible

    def test_the_common_formats_are_recognised(self):
        for suffixe in (".wav", ".m4a", ".mp3", ".opus", ".flac"):
            assert offer(
                Path(f"x{suffixe}"), 50_000_000, ALL
            ).destination is Destination.MEETING

    def test_too_short_a_sound_is_not_a_meeting(self):
        """Une notification système, un bip, un extrait."""
        propose = offer(Path("bip.wav"), MINIMUM_SOUND_SIZE - 1, ALL)
        assert propose.destination is Destination.UNKNOWN
        assert "trop court" in propose.because

    def test_the_threshold_stays_low(self):
        """A one-minute meeting already weighs 2 MB as WAV."""
        assert 50_000 <= MINIMUM_SOUND_SIZE <= 2_000_000


class TestVideos:
    def test_a_teams_recording_is_recognised(self):
        propose = offer(Path("Teams-2026-09-09.mp4"), 800_000_000, ALL)
        assert propose.destination is Destination.VIDEO
        assert propose.feasible

    def test_what_is_missing_is_named_rather_than_the_file_dropped(self):
        """Saying « ffmpeg would be needed » is more useful than making it vanish."""
        propose = offer(Path("x.mp4"), 10_000_000, frozenset())
        assert propose.destination is Destination.VIDEO
        assert not propose.feasible
        assert "ffmpeg" in propose.blocked_by


class TestDocumentsToFile:
    def test_a_text_reads_with_nothing_installed(self):
        propose = offer(Path("compte-rendu.md"), 4_000, frozenset())
        assert propose.destination is Destination.CONTEXT
        assert propose.feasible, "aucun outil n'est requis"

    def test_a_pdf_asks_for_a_tool(self):
        assert offer(Path("x.pdf"), 2_000_000, frozenset()).blocked_by
        assert offer(Path("x.pdf"), 2_000_000, ALL).feasible

    def test_an_office_document_asks_for_textutil(self):
        propose = offer(Path("x.docx"), 40_000, frozenset())
        assert "textutil" in propose.blocked_by


class TestWhatCannotBeFiled:
    def test_a_data_export_is_called_unknown(self):
        propose = offer(Path("export.csv"), 10_000, ALL)
        assert propose.destination is Destination.UNKNOWN
        assert ".csv" in propose.because

    def test_a_file_with_no_extension(self):
        propose = offer(Path("machin"), 1_000, ALL)
        assert propose.destination is Destination.UNKNOWN
        assert "sans extension" in propose.because

    def test_the_unknown_is_never_feasible(self):
        assert not offer(Path("x.zip"), 1_000, ALL).feasible


class TestTheSummaryOfABatch:
    def test_it_says_what_the_batch_will_become(self):
        propositions = [
            offer(Path("a.wav"), 50_000_000, ALL),
            offer(Path("b.mp4"), 50_000_000, ALL),
            offer(Path("c.md"), 4_000, ALL),
        ]
        sentence = summarise(propositions)
        assert "réunion" in sentence and "vidéo" in sentence and "contexte" in sentence

    def test_it_flags_what_is_waiting_for_a_tool(self):
        sentence = summarise([offer(Path("a.mp4"), 50_000_000, frozenset())])
        assert "attente d'un outil" in sentence

    def test_an_empty_batch_says_so(self):
        assert summarise([]) == "Aucun fichier."
