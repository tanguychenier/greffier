"""Sauvegarder, et surtout restaurer.

Une sauvegarde qu'on n'a jamais restaurée est une hypothèse. Ces tests jouent
l'aller **et** le retour.
"""

from datetime import UTC, datetime

import pytest

from greffier.application.back_up import do_it, lister, restore


def poser_des_donnees(racine):
    """Une installation vraisemblable : du texte, et de l'audio à ne pas prendre."""
    for folder, file, content in (
        ("banque-de-voix", "sophie.json", '{"nom": "Sophie"}'),
        ("reunions", "2026-09-09_10h05_reunion.json", '{"identifiant": "x"}'),
        ("comptes-rendus", "2026-09-09_10h05_reunion.md", "# Compte rendu"),
        ("transcriptions", "2026-09-09_10h05_reunion.txt", "Bonjour."),
        ("conversations", "2026-09-09_10h05_reunion.jsonl", '{"qui": "moi"}'),
    ):
        (racine / folder).mkdir(parents=True, exist_ok=True)
        (racine / folder / file).write_text(content, encoding="utf-8")
    (racine / "enregistrements").mkdir(parents=True, exist_ok=True)
    (racine / "enregistrements" / "gros.wav").write_bytes(b"x" * 200_000)
    (racine / "modeles").mkdir(parents=True, exist_ok=True)
    (racine / "modeles" / "modele.bin").write_bytes(b"y" * 200_000)
    return racine


def poser_la_config(racine):
    racine.mkdir(parents=True, exist_ok=True)
    for file in ("config.toml", "contexte.toml", "sujets.toml"):
        (racine / file).write_text(f"# {file}\n", encoding="utf-8")
    return racine


class TestCeQuiEstEmporte:
    def test_le_texte_est_pris(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        assert "banque-de-voix" in faite.dossiers
        assert "reunions" in faite.dossiers
        assert "comptes-rendus" in faite.dossiers

    def test_l_audio_n_est_pas_pris(self, tmp_path):
        """1,1 Go contre 3 Mo : c'est lui qui rend la sauvegarde possible."""
        data = poser_des_donnees(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        assert "enregistrements" not in faite.dossiers
        assert faite.bytes_read < 100_000, "l'archive doit rester légère"

    def test_les_modeles_ne_sont_pas_pris(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        assert "modeles" not in do_it(data, None, tmp_path / "copies").dossiers

    def test_la_configuration_et_les_registres_sont_pris(self, tmp_path):
        """Ils se réécrivent à la main : c'est ce qu'on veut éviter."""
        data = poser_des_donnees(tmp_path / "donnees")
        config = poser_la_config(tmp_path / "config")
        faite = do_it(data, config, tmp_path / "copies")
        assert "configuration" in faite.dossiers

    def test_une_installation_neuve_ne_fait_pas_echouer(self, tmp_path):
        """Ni conversations ni questions : ce n'est pas une anomalie."""
        empty = tmp_path / "vide"
        empty.mkdir()
        faite = do_it(empty, None, tmp_path / "copies")
        assert faite.archive.exists()
        assert faite.dossiers == ()


class TestRetour:
    """L'aller-retour complet, celui qu'on oublie de vérifier."""

    def test_ce_qui_est_sauvegarde_se_restaure(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        elsewhere = tmp_path / "ailleurs"
        remis = restore(faite.archive, elsewhere)
        assert "reunions" in remis
        assert (elsewhere / "comptes-rendus" / "2026-09-09_10h05_reunion.md").exists()
        assert (elsewhere / "transcriptions" / "2026-09-09_10h05_reunion.txt").read_text(
            encoding="utf-8") == "Bonjour."

    def test_restaurer_refuse_d_ecraser_par_defaut(self, tmp_path):
        """Restaurer la semaine dernière par-dessus le jour ferait plus de dégâts
        que la panne qu'on réparait."""
        data = poser_des_donnees(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        with pytest.raises(FileExistsError, match="rien n'a été touché"):
            restore(faite.archive, data)

    def test_ecraser_reste_possible_quand_on_le_demande(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "copies")
        assert restore(faite.archive, data, ecraser=True)

    def test_une_archive_absente_le_dit(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="introuvable"):
            restore(tmp_path / "jamais.tar.gz", tmp_path / "ailleurs")


class TestRotation:
    def test_les_anciennes_partent(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        copies = tmp_path / "copies"
        for jour in range(1, 6):
            do_it(data, None, copies, kept=3,
                  quand=datetime(2026, 9, jour, 12, 0, tzinfo=UTC))
        assert len(lister(copies)) == 3

    def test_la_plus_recente_survit_toujours(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        copies = tmp_path / "copies"
        for jour in (1, 2):
            do_it(data, None, copies, kept=0,
                  quand=datetime(2026, 9, jour, 12, 0, tzinfo=UTC))
        restantes = lister(copies)
        assert len(restantes) == 1
        assert "2026-09-02" in restantes[0][0]


class TestArchiveInterrompue:
    def test_aucune_archive_partielle_ne_reste(self, tmp_path):
        """Une archive tronquée ne doit pas passer pour valable."""
        data = poser_des_donnees(tmp_path / "donnees")
        copies = tmp_path / "copies"
        do_it(data, None, copies)
        assert not list(copies.glob("*.partiel"))


class TestOuEstEcriteLArchive:
    def test_le_meme_disque_est_signale(self, tmp_path):
        """Confondre « une copie existe » et « le travail est à l'abri » est la
        façon habituelle de n'avoir aucune sauvegarde le jour venu."""
        data = poser_des_donnees(tmp_path / "Greffier")
        faite = do_it(data, None, tmp_path / "Greffier" / "sauvegardes")
        assert faite.on_the_same_disk is True

    def test_un_dossier_ailleurs_ne_l_est_pas(self, tmp_path):
        data = poser_des_donnees(tmp_path / "donnees")
        faite = do_it(data, None, tmp_path / "disque-externe")
        assert faite.on_the_same_disk is False

    def test_un_dossier_qui_porte_le_nom_de_l_outil_n_est_pas_le_meme_disque(
        self, tmp_path
    ):
        """« Greffier-sauvegardes » dans un espace synchronisé contient le mot
        « Greffier » : chercher le mot prévenait qui avait fait ce qu'il faut."""
        data = poser_des_donnees(tmp_path / "Greffier")
        faite = do_it(data, None, tmp_path / "nuage" / "Greffier-sauvegardes")
        assert faite.on_the_same_disk is False
