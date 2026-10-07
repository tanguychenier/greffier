"""What is written when something fails, and what is not.

A tool used by many people receives « ça n'a pas marché » and nothing else.
What is missing is never the report, it is what the machine saw at that
instant. But an incidents file will only be attached to a report if it can
be without being reread: nothing personal enters it.
"""

from datetime import datetime

import pytest

from greffier.domain.trouble import Trouble, without_traces, worth_keeping


class TestWhatIsWritten:
    def test_a_line_carries_the_moment_the_place_and_the_reason(self):
        line = Trouble("transcription", "le modèle a refusé").line()
        assert "transcription" in line and "le modèle a refusé" in line
        # Trouble stamps the local wall-clock; the test reads the same clock.
        assert datetime.now().strftime("%Y-%m-%d") in line  # noqa: DTZ005

    def test_the_version_and_the_system_are_carried_when_they_are_known(self):
        line = Trouble("envoi", "serveur muet").line("0.3.22", "Linux x86_64")
        assert "0.3.22" in line and "Linux x86_64" in line

    def test_a_line_stays_one_line(self):
        """A twelve-line trace would make the file unreadable."""
        line = Trouble("chaîne", "première ligne\ndeuxième\ttroisième").line()
        assert "\n" not in line
        assert line.count("\t") == 2

    def test_an_incident_without_a_place_is_refused(self):
        with pytest.raises(ValueError, match=r"^un incident sans lieu ne se retrouve pas$"):
            Trouble("   ", "quelque chose")

    def test_the_columns_come_in_a_fixed_order(self):
        """Whoever sorts the file relies on it: moment, system, version, place, reason."""
        when = datetime(2026, 9, 9, 14, 5, 0)  # noqa: DTZ001  # naive, as Trouble's default
        line = Trouble("envoi", "serveur muet", when).line("0.3.22", "Linux x86_64")
        assert line.split("\t") == [
            "2026-09-09T14:05:00", "Linux x86_64", "0.3.22", "envoi", "serveur muet"]

    def test_a_break_or_a_tab_in_the_reason_becomes_one_space(self):
        when = datetime(2026, 9, 9, 14, 5, 0)  # noqa: DTZ001  # naive, as Trouble's default
        line = Trouble("chaîne", "première ligne\ndeuxième\ttroisième", when).line()
        assert line == "2026-09-09T14:05:00\tchaîne\tpremière ligne deuxième troisième"


class TestWhatIsNotWritten:
    def test_a_path_is_taken_out(self):
        """A path carries the account name, and often a meeting's subject."""
        without = without_traces("échec sur /home/quelqu-un/reunions/point-budget.wav")
        assert "quelqu-un" not in without and "point-budget" not in without
        assert "<chemin>" in without

    def test_a_windows_path_too(self):
        without = without_traces(r"échec sur C:\Users\quelqu-un\reunions\point.wav")
        assert "quelqu-un" not in without and "<chemin>" in without

    def test_an_address_is_taken_out(self):
        without = without_traces("envoi refusé pour quelqu-un@exemple.fr")
        assert "quelqu-un@exemple.fr" not in without and "<adresse>" in without

    def test_what_was_taken_out_is_named_in_its_place(self):
        """Whoever reads the line knows a path or an address stood there."""
        assert without_traces("échec sur /home/quelqu-un/reunions/point-budget.wav") == (
            "échec sur <chemin>")
        assert without_traces("envoi refusé pour quelqu-un@exemple.fr") == (
            "envoi refusé pour <adresse>")

    def test_what_carries_nothing_private_is_kept_whole(self):
        assert without_traces("le modèle a refusé le format") == "le modèle a refusé le format"

    def test_the_stripping_happens_on_the_filed_line(self):
        line = Trouble("envoi", "pour quelqu-un@exemple.fr").line()
        assert "exemple.fr" not in line


class TestTheFileDoesNotGrow:
    def test_only_the_last_ones_are_kept(self):
        lines = [f"ligne {n}" for n in range(500)]
        kept_ones = worth_keeping(lines, 200)
        assert len(kept_ones) == 200
        assert kept_ones[-1] == "ligne 499"

    def test_a_short_file_is_kept_whole(self):
        assert worth_keeping(["une", "deux"], 200) == ["une", "deux"]

    def test_keeping_nothing_is_allowed(self):
        assert worth_keeping(["une"], 0) == []

    def test_keeping_one_keeps_the_last(self):
        assert worth_keeping(["une", "deux"], 1) == ["deux"]

    def test_two_hundred_are_kept_when_nobody_says_how_many(self):
        assert len(worth_keeping([f"ligne {n}" for n in range(500)])) == 200
