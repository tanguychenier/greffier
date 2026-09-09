"""Sauvegarder, et surtout restaurer.

Une sauvegarde qu'on n'a jamais restaurée est une hypothèse. Ces tests jouent
l'aller **et** le retour.
"""

from datetime import UTC, datetime

import pytest

from greffier.application.sauvegarder import faire, lister, restaurer


def poser_des_donnees(racine):
    """Une installation vraisemblable : du texte, et de l'audio à ne pas prendre."""
    for dossier, fichier, contenu in (
        ("banque-de-voix", "sophie.json", '{"nom": "Sophie"}'),
        ("reunions", "2026-09-09_10h05_reunion.json", '{"identifiant": "x"}'),
        ("comptes-rendus", "2026-09-09_10h05_reunion.md", "# Compte rendu"),
        ("transcriptions", "2026-09-09_10h05_reunion.txt", "Bonjour."),
        ("conversations", "2026-09-09_10h05_reunion.jsonl", '{"qui": "moi"}'),
    ):
        (racine / dossier).mkdir(parents=True, exist_ok=True)
        (racine / dossier / fichier).write_text(contenu, encoding="utf-8")
    (racine / "enregistrements").mkdir(parents=True, exist_ok=True)
    (racine / "enregistrements" / "gros.wav").write_bytes(b"x" * 200_000)
    (racine / "modeles").mkdir(parents=True, exist_ok=True)
    (racine / "modeles" / "modele.bin").write_bytes(b"y" * 200_000)
    return racine


def poser_la_config(racine):
    racine.mkdir(parents=True, exist_ok=True)
    for fichier in ("config.toml", "contexte.toml", "sujets.toml"):
        (racine / fichier).write_text(f"# {fichier}\n", encoding="utf-8")
    return racine


class TestCeQuiEstEmporte:
    def test_le_texte_est_pris(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        faite = faire(donnees, None, tmp_path / "copies")
        assert "banque-de-voix" in faite.dossiers
        assert "reunions" in faite.dossiers
        assert "comptes-rendus" in faite.dossiers

    def test_l_audio_n_est_pas_pris(self, tmp_path):
        """1,1 Go contre 3 Mo : c'est lui qui rend la sauvegarde possible."""
        donnees = poser_des_donnees(tmp_path / "donnees")
        faite = faire(donnees, None, tmp_path / "copies")
        assert "enregistrements" not in faite.dossiers
        assert faite.octets < 100_000, "l'archive doit rester légère"

    def test_les_modeles_ne_sont_pas_pris(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        assert "modeles" not in faire(donnees, None, tmp_path / "copies").dossiers

    def test_la_configuration_et_les_registres_sont_pris(self, tmp_path):
        """Ils se réécrivent à la main : c'est ce qu'on veut éviter."""
        donnees = poser_des_donnees(tmp_path / "donnees")
        config = poser_la_config(tmp_path / "config")
        faite = faire(donnees, config, tmp_path / "copies")
        assert "configuration" in faite.dossiers

    def test_une_installation_neuve_ne_fait_pas_echouer(self, tmp_path):
        """Ni conversations ni questions : ce n'est pas une anomalie."""
        vide = tmp_path / "vide"
        vide.mkdir()
        faite = faire(vide, None, tmp_path / "copies")
        assert faite.archive.exists()
        assert faite.dossiers == ()


class TestRetour:
    """L'aller-retour complet, celui qu'on oublie de vérifier."""

    def test_ce_qui_est_sauvegarde_se_restaure(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        faite = faire(donnees, None, tmp_path / "copies")
        ailleurs = tmp_path / "ailleurs"
        remis = restaurer(faite.archive, ailleurs)
        assert "reunions" in remis
        assert (ailleurs / "comptes-rendus" / "2026-09-09_10h05_reunion.md").exists()
        assert (ailleurs / "transcriptions" / "2026-09-09_10h05_reunion.txt").read_text(
            encoding="utf-8") == "Bonjour."

    def test_restaurer_refuse_d_ecraser_par_defaut(self, tmp_path):
        """Restaurer la semaine dernière par-dessus le jour ferait plus de dégâts
        que la panne qu'on réparait."""
        donnees = poser_des_donnees(tmp_path / "donnees")
        faite = faire(donnees, None, tmp_path / "copies")
        with pytest.raises(FileExistsError, match="rien n'a été touché"):
            restaurer(faite.archive, donnees)

    def test_ecraser_reste_possible_quand_on_le_demande(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        faite = faire(donnees, None, tmp_path / "copies")
        assert restaurer(faite.archive, donnees, ecraser=True)

    def test_une_archive_absente_le_dit(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="introuvable"):
            restaurer(tmp_path / "jamais.tar.gz", tmp_path / "ailleurs")


class TestRotation:
    def test_les_anciennes_partent(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        copies = tmp_path / "copies"
        for jour in range(1, 6):
            faire(donnees, None, copies, gardees=3,
                  quand=datetime(2026, 9, jour, 12, 0, tzinfo=UTC))
        assert len(lister(copies)) == 3

    def test_la_plus_recente_survit_toujours(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        copies = tmp_path / "copies"
        for jour in (1, 2):
            faire(donnees, None, copies, gardees=0,
                  quand=datetime(2026, 9, jour, 12, 0, tzinfo=UTC))
        restantes = lister(copies)
        assert len(restantes) == 1
        assert "2026-09-02" in restantes[0][0]


class TestArchiveInterrompue:
    def test_aucune_archive_partielle_ne_reste(self, tmp_path):
        """Une archive tronquée ne doit pas passer pour valable."""
        donnees = poser_des_donnees(tmp_path / "donnees")
        copies = tmp_path / "copies"
        faire(donnees, None, copies)
        assert not list(copies.glob("*.partiel"))


class TestOuEstEcriteLArchive:
    def test_le_meme_disque_est_signale(self, tmp_path):
        """Confondre « une copie existe » et « le travail est à l'abri » est la
        façon habituelle de n'avoir aucune sauvegarde le jour venu."""
        donnees = poser_des_donnees(tmp_path / "Greffier")
        faite = faire(donnees, None, tmp_path / "Greffier" / "sauvegardes")
        assert faite.sur_le_meme_disque is True

    def test_un_dossier_ailleurs_ne_l_est_pas(self, tmp_path):
        donnees = poser_des_donnees(tmp_path / "donnees")
        faite = faire(donnees, None, tmp_path / "disque-externe")
        assert faite.sur_le_meme_disque is False

    def test_un_dossier_qui_porte_le_nom_de_l_outil_n_est_pas_le_meme_disque(
        self, tmp_path
    ):
        """« Greffier-sauvegardes » dans un espace synchronisé contient le mot
        « Greffier » : chercher le mot prévenait qui avait fait ce qu'il faut."""
        donnees = poser_des_donnees(tmp_path / "Greffier")
        faite = faire(donnees, None, tmp_path / "nuage" / "Greffier-sauvegardes")
        assert faite.sur_le_meme_disque is False
