"""Backing up, and above all restoring.

A backup nobody ever restored is a hypothesis. These tests play the journey out
**and** back.
"""

from datetime import UTC, datetime

import pytest

from greffier.application.back_up import do_it, lister, restore


def lay_out_some_data(root):
    """A believable installation: some text, and audio that must not be taken."""
    for folder, file, content in (
        ("banque-de-voix", "sophie.json", '{"nom": "Sophie"}'),
        ("reunions", "2026-09-09_10h05_reunion.json", '{"identifiant": "x"}'),
        ("comptes-rendus", "2026-09-09_10h05_reunion.md", "# Compte rendu"),
        ("transcriptions", "2026-09-09_10h05_reunion.txt", "Bonjour."),
        ("conversations", "2026-09-09_10h05_reunion.jsonl", '{"qui": "moi"}'),
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / file).write_text(content, encoding="utf-8")
    (root / "enregistrements").mkdir(parents=True, exist_ok=True)
    (root / "enregistrements" / "gros.wav").write_bytes(b"x" * 200_000)
    (root / "modeles").mkdir(parents=True, exist_ok=True)
    (root / "modeles" / "modele.bin").write_bytes(b"y" * 200_000)
    return root


def lay_out_the_config(root):
    root.mkdir(parents=True, exist_ok=True)
    for file in ("config.toml", "contexte.toml", "sujets.toml"):
        (root / file).write_text(f"# {file}\n", encoding="utf-8")
    return root


class TestWhatIsCarriedAway:
    def test_the_text_is_taken(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        assert "banque-de-voix" in faite.dossiers
        assert "reunions" in faite.dossiers
        assert "comptes-rendus" in faite.dossiers

    def test_the_audio_is_not_taken(self, tmp_path):
        """1.1 GB against 3 MB: it is what makes the backup possible at all."""
        data = lay_out_some_data(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        assert "enregistrements" not in faite.dossiers
        assert faite.bytes_read < 100_000, "l'archive doit rester légère"

    def test_the_models_are_not_taken(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        assert "modeles" not in do_it(data, None, tmp_path / "copies").dossiers

    def test_the_settings_and_the_registers_are_taken(self, tmp_path):
        """They would have to be typed again by hand: that is what to avoid."""
        data = lay_out_some_data(tmp_path / "donnees")
        config = lay_out_the_config(tmp_path / "config")
        faite = do_it(data, config, tmp_path / "copies")
        assert "configuration" in faite.dossiers

    def test_a_fresh_installation_does_not_make_it_fail(self, tmp_path):
        """Neither conversations nor questions: that is not an anomaly."""
        empty = tmp_path / "vide"
        empty.mkdir()
        faite = do_it(empty, None, tmp_path / "copies")
        assert faite.archive.exists()
        assert faite.dossiers == ()


class TestRestoring:
    """L'aller-retour complet, celui qu'on oublie de vérifier."""

    def test_what_was_backed_up_restores(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        elsewhere = tmp_path / "ailleurs"
        remis = restore(faite.archive, elsewhere)
        assert "reunions" in remis
        assert (elsewhere / "comptes-rendus" / "2026-09-09_10h05_reunion.md").exists()
        assert (elsewhere / "transcriptions" / "2026-09-09_10h05_reunion.txt").read_text(
            encoding="utf-8") == "Bonjour."

    def test_restoring_refuses_to_overwrite_by_default(self, tmp_path):
        """Restoring last week over today would do more damage than the failure being
        repaired.
        """
        data = lay_out_some_data(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        with pytest.raises(FileExistsError, match="rien n'a été touché"):
            restore(faite.archive, data)

    def test_overwriting_stays_possible_when_asked_for(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        assert restore(faite.archive, data, ecraser=True)

    def test_a_missing_archive_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="introuvable"):
            restore(tmp_path / "jamais.tar.gz", tmp_path / "ailleurs")


class TestKeepingOnlySoMany:
    def test_the_old_ones_go(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        copies = tmp_path / "copies"
        for jour in range(1, 6):
            do_it(data, None, copies, kept=3,
                  when=datetime(2026, 9, jour, 12, 0, tzinfo=UTC))
        assert len(lister(copies)) == 3

    def test_the_most_recent_one_always_survives(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        copies = tmp_path / "copies"
        for jour in (1, 2):
            do_it(data, None, copies, kept=0,
                  when=datetime(2026, 9, jour, 12, 0, tzinfo=UTC))
        restantes = lister(copies)
        assert len(restantes) == 1
        assert "2026-09-02" in restantes[0][0]


class TestAnArchiveCutShort:
    def test_no_half_written_archive_is_left(self, tmp_path):
        """A truncated archive must not pass for a valid one."""
        data = lay_out_some_data(tmp_path / "donnees")
        copies = tmp_path / "copies"
        do_it(data, None, copies)
        assert not list(copies.glob("*.partiel"))


class TestWhereTheArchiveIsWritten:
    def test_the_same_disk_is_flagged(self, tmp_path):
        """Confusing "a copy exists" with "the work is safe" is the usual way of having no
        backup at all on the day it matters.
        """
        data = lay_out_some_data(tmp_path / "Greffier")
        faite = do_it(data, None, tmp_path / "Greffier" / "sauvegardes")
        assert faite.on_the_same_disk is True

    def test_a_folder_elsewhere_is_not(self, tmp_path):
        data = lay_out_some_data(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "disque-externe")
        assert faite.on_the_same_disk is False

    def test_a_folder_named_after_the_tool_is_not_the_same_disk(
        self, tmp_path
    ):
        """"Greffier-sauvegardes" in a synchronised space holds the word "Greffier":
        looking for the word warned whoever had done the right thing.
        """
        data = lay_out_some_data(tmp_path / "Greffier")
        faite = do_it(data, None, tmp_path / "nuage" / "Greffier-sauvegardes")
        assert faite.on_the_same_disk is False
