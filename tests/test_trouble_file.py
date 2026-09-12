"""Le fichier d'incidents : ce qu'il garde, et ce qu'il ne fait jamais tomber."""

from __future__ import annotations

from greffier.adapters.trouble_file import KEPT, TroubleFile


class TestIlEcrit:
    def test_an_incident_reaches_the_file(self, tmp_path):
        journal = TroubleFile(tmp_path / "incidents.log", "0.3.22")
        journal.note("transcription", "le modèle a refusé")
        assert "le modèle a refusé" in (tmp_path / "incidents.log").read_text()

    def test_the_folder_is_made_if_it_is_missing(self, tmp_path):
        journal = TroubleFile(tmp_path / "pas" / "encore" / "incidents.log")
        journal.note("chaîne", "quelque chose")
        assert journal.file.exists()

    def test_the_newest_is_last(self, tmp_path):
        journal = TroubleFile(tmp_path / "incidents.log")
        journal.note("un", "premier")
        journal.note("deux", "second")
        assert "second" in journal.read()[-1]


class TestIlNeTombeJamais:
    def test_a_folder_that_cannot_be_written_costs_nothing(self, tmp_path):
        """Un journal ne vaut pas une réunion : il se tait plutôt que d'échouer."""
        obstacle = tmp_path / "obstacle"
        obstacle.write_text("je ne suis pas un dossier")
        TroubleFile(obstacle / "incidents.log").note("chaîne", "quelque chose")

    def test_reading_a_file_that_is_not_there_gives_nothing(self, tmp_path):
        assert TroubleFile(tmp_path / "absent.log").read() == []

    def test_an_incident_without_a_place_is_swallowed(self, tmp_path):
        """Le domaine refuse, l'adaptateur se tait : personne ne perd sa réunion."""
        TroubleFile(tmp_path / "incidents.log").note("  ", "quelque chose")
        assert not (tmp_path / "incidents.log").exists()


class TestIlNeGrossitPas:
    def test_the_file_is_brought_back_to_what_is_kept(self, tmp_path):
        journal = TroubleFile(tmp_path / "incidents.log")
        for n in range(KEPT * 2 + 5):
            journal.note("chaîne", f"incident {n}")
        lignes = (tmp_path / "incidents.log").read_text().splitlines()
        assert len(lignes) <= KEPT + 5
        assert f"incident {KEPT * 2 + 4}" in lignes[-1]
