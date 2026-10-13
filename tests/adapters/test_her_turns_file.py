"""When the assistant spoke, kept for the processing that comes after."""

from __future__ import annotations

from greffier.adapters import her_turns_file as turns


class TestKeepingHerTurns:
    def test_what_is_written_is_read_back(self, tmp_path):
        file = turns.file_for(tmp_path, "2026-09-12_reunion")
        turns.keep(file, 12.0, 18.4)
        assert turns.read(file) == [(12.0, 18.4)]

    def test_they_pile_up_in_order(self, tmp_path):
        file = turns.file_for(tmp_path, "r")
        for depart in (10.0, 30.0, 50.0):
            turns.keep(file, depart, depart + 4.0)
        assert [start for start, _ in turns.read(file)] == [10.0, 30.0, 50.0]

    def test_an_empty_turn_is_not_kept(self, tmp_path):
        file = turns.file_for(tmp_path, "r")
        turns.keep(file, 12.0, 12.0)
        assert turns.read(file) == []

    def test_a_broken_line_is_passed_over(self, tmp_path):
        file = turns.file_for(tmp_path, "r")
        turns.keep(file, 10.0, 14.0)
        with file.open("a", encoding="utf-8") as output_:
            output_.write("{cassé\n")
        turns.keep(file, 30.0, 34.0)
        assert len(turns.read(file)) == 2

    def test_a_meeting_where_she_never_spoke_reads_empty(self, tmp_path):
        assert turns.read(turns.file_for(tmp_path, "muette")) == []

    def test_a_folder_it_cannot_write_costs_no_answer(self, tmp_path):
        """She is talking: a file is not a reason to stop her."""
        forbidden_one = tmp_path / "fichier"
        forbidden_one.write_text("", encoding="utf-8")
        turns.keep(forbidden_one / "sous" / "r.jsonl", 1.0, 2.0)
