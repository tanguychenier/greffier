"""Ce qu'on écrit quand quelque chose rate, et ce qu'on n'écrit pas.

Un outil employé par beaucoup de gens reçoit « ça n'a pas marché » et rien
d'autre. Ce qui manque n'est jamais le rapport, c'est ce que la machine voyait
à cet instant. Mais un fichier d'incidents ne sera joint à un rapport que s'il
peut l'être sans être relu : rien de personnel n'y entre.
"""

from datetime import datetime

import pytest

from greffier.domain.trouble import Trouble, without_traces, worth_keeping


class TestCeQuOnEcrit:
    def test_a_line_carries_the_moment_the_place_and_the_reason(self):
        ligne = Trouble("transcription", "le modèle a refusé").line()
        assert "transcription" in ligne and "le modèle a refusé" in ligne
        assert datetime.now().strftime("%Y-%m-%d") in ligne

    def test_the_version_and_the_system_are_carried_when_they_are_known(self):
        ligne = Trouble("envoi", "serveur muet").line("0.3.22", "Linux x86_64")
        assert "0.3.22" in ligne and "Linux x86_64" in ligne

    def test_a_line_stays_one_line(self):
        """Une trace sur douze lignes rendrait le fichier illisible."""
        ligne = Trouble("chaîne", "première ligne\ndeuxième\ttroisième").line()
        assert "\n" not in ligne
        assert ligne.count("\t") == 2

    def test_an_incident_without_a_place_is_refused(self):
        with pytest.raises(ValueError):
            Trouble("   ", "quelque chose")


class TestCeQuOnNEcritPas:
    def test_a_path_is_taken_out(self):
        """Un chemin porte le nom du compte, et souvent le sujet d'une réunion."""
        sans = without_traces("échec sur /home/quelqu-un/reunions/point-budget.wav")
        assert "quelqu-un" not in sans and "point-budget" not in sans
        assert "<chemin>" in sans

    def test_a_windows_path_too(self):
        sans = without_traces(r"échec sur C:\Users\quelqu-un\reunions\point.wav")
        assert "quelqu-un" not in sans and "<chemin>" in sans

    def test_an_address_is_taken_out(self):
        sans = without_traces("envoi refusé pour quelqu-un@exemple.fr")
        assert "quelqu-un@exemple.fr" not in sans and "<adresse>" in sans

    def test_what_carries_nothing_private_is_kept_whole(self):
        assert without_traces("le modèle a refusé le format") == "le modèle a refusé le format"

    def test_the_stripping_happens_on_the_filed_line(self):
        ligne = Trouble("envoi", "pour quelqu-un@exemple.fr").line()
        assert "exemple.fr" not in ligne


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
