"""The catalogues of what the tool says: one file per language, same keys."""

from __future__ import annotations

import pytest

from greffier.adapters import wording_files
from greffier.domain.tongue import FALLBACK, SPOKEN


class TestTheCataloguesAgree:
    def test_every_spoken_language_has_a_catalogue(self):
        assert set(SPOKEN) <= set(wording_files.translated())

    @pytest.mark.parametrize("language", SPOKEN)
    def test_no_language_is_missing_a_key(self, language):
        """Nothing checks a TOML file, so this does: a key added to the
        reference and forgotten elsewhere would silently show English."""
        manquantes = wording_files.wording(language).missing()
        assert not manquantes, f"{language} : {manquantes}"

    @pytest.mark.parametrize("language", SPOKEN)
    def test_no_language_carries_a_key_nobody_else_has(self, language):
        """A key in one file only is a key the code does not use."""
        reference = set(wording_files.read(FALLBACK))
        assert set(wording_files.read(language)) <= reference

    def test_the_sentences_differ_between_languages(self):
        """A catalogue copied and not translated is worse than none."""
        fr, en = wording_files.read("fr"), wording_files.read("en")
        identiques = {c for c in fr if fr[c] == en.get(c)}
        assert len(identiques) < len(fr) / 3, f"trop de phrases non traduites : {identiques}"


class TestReadingOne:
    def test_the_sections_are_flattened(self):
        """`[fenetre]` then `demarrer =` in the file, `fenetre.demarrer` in the code."""
        assert "fenetre.demarrer" in wording_files.read("fr")

    def test_a_language_with_no_file_is_empty_not_an_error(self):
        assert wording_files.read("xx") == {}

    def test_a_broken_file_costs_its_sentences_and_not_the_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wording_files, "CATALOGUES", tmp_path)
        (tmp_path / "zz.toml").write_text("[fenetre\nbrisé", encoding="utf-8")
        assert wording_files.read("zz") == {}
