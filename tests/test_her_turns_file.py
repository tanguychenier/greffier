"""When the assistant spoke, kept for the processing that comes after."""

from __future__ import annotations

from greffier.adapters import her_turns_file as fichier


class TestKeepingHerTurns:
    def test_what_is_written_is_read_back(self, tmp_path):
        file = fichier.file_for(tmp_path, "2026-09-12_reunion")
        fichier.keep(file, 12.0, 18.4)
        assert fichier.read(file) == [(12.0, 18.4)]

    def test_they_pile_up_in_order(self, tmp_path):
        file = fichier.file_for(tmp_path, "r")
        for depart in (10.0, 30.0, 50.0):
            fichier.keep(file, depart, depart + 4.0)
        assert [debut for debut, _ in fichier.read(file)] == [10.0, 30.0, 50.0]

    def test_an_empty_turn_is_not_kept(self, tmp_path):
        file = fichier.file_for(tmp_path, "r")
        fichier.keep(file, 12.0, 12.0)
        assert fichier.read(file) == []

    def test_a_broken_line_is_passed_over(self, tmp_path):
        file = fichier.file_for(tmp_path, "r")
        fichier.keep(file, 10.0, 14.0)
        with file.open("a", encoding="utf-8") as sortie:
            sortie.write("{cassé\n")
        fichier.keep(file, 30.0, 34.0)
        assert len(fichier.read(file)) == 2

    def test_a_meeting_where_she_never_spoke_reads_empty(self, tmp_path):
        assert fichier.read(fichier.file_for(tmp_path, "muette")) == []

    def test_a_folder_it_cannot_write_costs_no_answer(self, tmp_path):
        """She is talking: a file is not a reason to stop her."""
        interdit = tmp_path / "fichier"
        interdit.write_text("", encoding="utf-8")
        fichier.keep(interdit / "sous" / "r.jsonl", 1.0, 2.0)
