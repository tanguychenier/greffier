"""Preparations on disk, and the one a meeting starting now would open on."""

from __future__ import annotations

from dataclasses import replace

from greffier.adapters import preparations_file as fichiers


class TestOnDisk:
    def test_what_is_written_is_read_back(self, tmp_path):
        preparation = fichiers.open_one(tmp_path, "point recette")
        fichiers.write(tmp_path, preparation.expecting("Sophie").raising("les anomalies"))
        relue = fichiers.read(tmp_path, preparation.identifier)
        assert relue.expected == ("Sophie",) and relue.to_raise == ("les anomalies",)

    def test_the_file_is_readable_by_a_person(self, tmp_path):
        preparation = fichiers.open_one(tmp_path, "point de recette")
        texte = fichiers.file_for(tmp_path, preparation.identifier).read_text("utf-8")
        assert "point de recette" in texte and "\n" in texte, "indenté, pas compacté"

    def test_a_file_a_person_broke_is_passed_over(self, tmp_path):
        fichiers.file_for(tmp_path, "cassee").write_text("{pas du json", encoding="utf-8")
        assert fichiers.read(tmp_path, "cassee") is None
        assert fichiers.lister(tmp_path) == []

    def test_nothing_at_all_is_not_an_error(self, tmp_path):
        assert fichiers.lister(tmp_path / "rien") == []
        assert fichiers.waiting(tmp_path / "rien") is None


class TestWhichOneAMeetingTakes:
    def test_the_most_recent_that_nobody_has_taken(self, tmp_path):
        ancienne = fichiers.open_one(tmp_path, "ancienne").raising("a")
        fichiers.write(tmp_path, ancienne)
        recente = fichiers.open_one(tmp_path, "récente").raising("b")
        # Deux préparations dans la même minute portent le même nom : on force
        # ici ce que l'horloge ferait d'elle-même une minute plus tard.
        recente = replace(recente, identifier="2026-12-31_23h59_preparation")
        fichiers.write(tmp_path, recente)
        assert fichiers.waiting(tmp_path).subject == "récente"

    def test_one_already_taken_is_not_offered_again(self, tmp_path):
        preparation = fichiers.open_one(tmp_path, "recette").raising("un point")
        fichiers.write(tmp_path, preparation.taken("2026-09-12_reunion"))
        assert fichiers.waiting(tmp_path) is None

    def test_one_that_gathered_nothing_is_not_offered(self, tmp_path):
        """Opening a preparation and saying nothing is not preparing."""
        fichiers.open_one(tmp_path, "ouverte pour rien")
        assert fichiers.waiting(tmp_path) is None
