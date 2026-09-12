"""The file that carries what earlier meetings left."""

from __future__ import annotations

from greffier.adapters import memory_file
from greffier.domain.memory import Trace


def _trace(numero: int) -> Trace:
    return Trace(
        identifier=f"2026-09-{numero:02d}_reunion",
        title=f"réunion {numero}",
        held_on=f"2026-09-{numero:02d}",
        decisions=(f"décision {numero}",),
    )


class TestOneLinePerMeeting:
    def test_what_is_written_is_read_back(self, tmp_path):
        file = memory_file.file_in(tmp_path)
        memory_file.remember(file, _trace(11))
        (relu,) = memory_file.recall(file)
        assert relu == _trace(11)

    def test_a_meeting_that_left_nothing_is_not_filed(self, tmp_path):
        file = memory_file.file_in(tmp_path)
        memory_file.remember(file, Trace(identifier="x", title="rien"))
        assert memory_file.recall(file) == []

    def test_the_most_recent_comes_first(self, tmp_path):
        """The writer reads from the top: the last meeting matters most."""
        file = memory_file.file_in(tmp_path)
        for numero in (9, 10, 11):
            memory_file.remember(file, _trace(numero))
        assert [t.title for t in memory_file.recall(file)] == [
            "réunion 11", "réunion 10", "réunion 9",
        ]

    def test_only_the_last_ones_are_read_back(self, tmp_path):
        file = memory_file.file_in(tmp_path)
        for numero in range(1, 20):
            memory_file.remember(file, _trace(numero))
        assert len(memory_file.recall(file, limit=3)) == 3

    def test_a_line_a_person_broke_is_passed_over(self, tmp_path):
        """The file is meant to be opened and corrected by hand."""
        file = memory_file.file_in(tmp_path)
        memory_file.remember(file, _trace(11))
        with file.open("a", encoding="utf-8") as sortie:
            sortie.write("{ceci n'est pas du json\n\n")
        memory_file.remember(file, _trace(12))
        assert [t.title for t in memory_file.recall(file)] == ["réunion 12", "réunion 11"]

    def test_no_file_is_not_an_error(self, tmp_path):
        assert memory_file.recall(tmp_path / "rien.jsonl") == []

    def test_the_accents_survive_the_round_trip(self, tmp_path):
        file = memory_file.file_in(tmp_path)
        memory_file.remember(file, Trace(
            identifier="x", title="réunion", decisions=("décalé à jeudi",)))
        assert memory_file.recall(file)[0].decisions == ("décalé à jeudi",)
        assert "décalé" in file.read_text(encoding="utf-8"), "lisible à l'œil nu"
