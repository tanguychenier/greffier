"""What is written when something fails, and what is not.

A tool used by many people receives « ça n'a pas marché » and nothing else.
What is missing is never the report, it is what the machine saw at that
instant. But an incidents file will only be attached to a report if it can
be without being reread: nothing personal enters it.
"""

from datetime import datetime

import pytest

from greffier.domain.trouble import Trouble, without_traces, worth_keeping


class TestCeQuOnEcrit:
    def test_a_line_carries_the_moment_the_place_and_the_reason(self):
        line = Trouble("transcription", "le modèle a refusé").line()
        assert "transcription" in line and "le modèle a refusé" in line
        assert datetime.now().strftime("%Y-%m-%d") in line

    def test_the_version_and_the_system_are_carried_when_they_are_known(self):
        line = Trouble("envoi", "serveur muet").line("0.3.22", "Linux x86_64")
        assert "0.3.22" in line and "Linux x86_64" in line

    def test_a_line_stays_one_line(self):
        """A twelve-line trace would make the file unreadable."""
        line = Trouble("chaîne", "première ligne\ndeuxième\ttroisième").line()
        assert "\n" not in line
        assert line.count("\t") == 2

    def test_an_incident_without_a_place_is_refused(self):
        with pytest.raises(ValueError):
            Trouble("   ", "quelque chose")


class TestCeQuOnNEcritPas:
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

    def test_what_carries_nothing_private_is_kept_whole(self):
        assert without_traces("le modèle a refusé le format") == "le modèle a refusé le format"

    def test_the_stripping_happens_on_the_filed_line(self):
        line = Trouble("envoi", "pour quelqu-un@exemple.fr").line()
        assert "exemple.fr" not in line


class TestLeFichierNeGrossitPas:
    def test_only_the_last_ones_are_kept(self):
        lignes = [f"ligne {n}" for n in range(500)]
        gardees = worth_keeping(lignes, 200)
        assert len(gardees) == 200
        assert gardees[-1] == "ligne 499"

    def test_a_short_file_is_kept_whole(self):
        assert worth_keeping(["une", "deux"], 200) == ["une", "deux"]

    def test_keeping_nothing_is_allowed(self):
        assert worth_keeping(["une"], 0) == []
