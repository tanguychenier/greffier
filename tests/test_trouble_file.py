"""The incidents file: what it keeps, and what it never brings down."""

from __future__ import annotations

from greffier.adapters.trouble_file import KEPT, TroubleFile


class TestIlEcrit:
    def test_an_incident_reaches_the_file(self, tmp_path):
        log = TroubleFile(tmp_path / "incidents.log", "0.3.22")
        log.note("transcription", "le modèle a refusé")
        assert "le modèle a refusé" in (tmp_path / "incidents.log").read_text()

    def test_the_folder_is_made_if_it_is_missing(self, tmp_path):
        log = TroubleFile(tmp_path / "pas" / "encore" / "incidents.log")
        log.note("chaîne", "quelque chose")
        assert log.file.exists()

    def test_the_newest_is_last(self, tmp_path):
        log = TroubleFile(tmp_path / "incidents.log")
        log.note("un", "premier")
        log.note("deux", "second")
        assert "second" in log.read()[-1]


class TestIlNeTombeJamais:
    def test_a_folder_that_cannot_be_written_costs_nothing(self, tmp_path):
        """A log is not worth a meeting: it keeps quiet rather than fail."""
        obstacle = tmp_path / "obstacle"
        obstacle.write_text("je ne suis pas un dossier")
        TroubleFile(obstacle / "incidents.log").note("chaîne", "quelque chose")

    def test_reading_a_file_that_is_not_there_gives_nothing(self, tmp_path):
        assert TroubleFile(tmp_path / "absent.log").read() == []

    def test_an_incident_without_a_place_is_swallowed(self, tmp_path):
        """The domain refuses, the adapter keeps quiet: nobody loses their meeting."""
        TroubleFile(tmp_path / "incidents.log").note("  ", "quelque chose")
        assert not (tmp_path / "incidents.log").exists()


class TestIlNeGrossitPas:
    def test_the_file_is_brought_back_to_what_is_kept(self, tmp_path):
        log = TroubleFile(tmp_path / "incidents.log")
        for n in range(KEPT * 2 + 5):
            log.note("chaîne", f"incident {n}")
        lignes = (tmp_path / "incidents.log").read_text().splitlines()
        assert len(lignes) <= KEPT + 5
        assert f"incident {KEPT * 2 + 4}" in lignes[-1]
