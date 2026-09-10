"""Ce qu'une sauvegarde emporte, et ce qu'elle laisse."""

from datetime import datetime

from greffier.domain.backup import (
    CONTENT,
    ECARTES,
    KEPT,
    BackupName,
    to_erase,
)


class TestContenu:
    def test_la_banque_de_voix_vient_en_premier(self):
        """Elle a été construite un nom à la fois : rien ne la refera."""
        assert CONTENT[0] == "banque-de-voix"

    def test_l_audio_est_ecarte(self):
        """C'est lui qui rend une sauvegarde impossible : 115 Mo par heure."""
        assert "enregistrements" in ECARTES
        assert "enregistrements" not in CONTENT

    def test_les_modeles_sont_ecartes(self):
        assert "modeles" in ECARTES

    def test_chaque_exclusion_dit_pourquoi(self):
        """Une sauvegarde qui grossit sans raison connue finit par ne plus se faire."""
        for folder, because in ECARTES.items():
            assert len(because) > 20, folder

    def test_rien_n_est_a_la_fois_pris_et_ecarte(self):
        assert not set(CONTENT) & set(ECARTES)

    def test_ce_qui_porte_le_travail_est_pris(self):
        for essentiel in ("reunions", "comptes-rendus", "transcriptions",
                          "conversations"):
            assert essentiel in CONTENT


class TestNom:
    def test_le_nom_porte_la_date_a_la_minute(self):
        """Deux sauvegardes du même jour doivent pouvoir coexister."""
        name = BackupName(datetime(2026, 9, 9, 14, 5))
        assert str(name) == "greffier-2026-09-09_14h05"

    def test_le_nom_se_relit(self):
        when = datetime(2026, 9, 9, 14, 5)
        assert BackupName.read(str(BackupName(when))) == when

    def test_ce_qui_n_est_pas_une_sauvegarde_est_refuse(self):
        assert BackupName.read("mes-documents") is None
        assert BackupName.read("greffier-pas-une-date") is None


class TestRotation:
    def names(self, how_many: int) -> list[str]:
        return [str(BackupName(datetime(2026, 9, jour, 12, 0))) for jour in range(1, how_many + 1)]

    def test_sous_le_compte_rien_n_est_efface(self):
        assert to_erase(self.names(3), kept=7) == []

    def test_les_plus_anciennes_partent(self):
        a_partir = to_erase(self.names(10), kept=7)
        assert len(a_partir) == 3
        assert "greffier-2026-09-01_12h00" in a_partir
        assert "greffier-2026-09-10_12h00" not in a_partir

    def test_la_plus_recente_ne_part_jamais(self):
        """Une rotation qui peut tout effacer est une purge, pas une rotation."""
        names = self.names(5)
        a_partir = to_erase(names, kept=0)
        assert "greffier-2026-09-05_12h00" not in a_partir
        assert len(a_partir) == 4

    def test_ce_qui_n_est_pas_une_sauvegarde_est_laisse(self):
        """On efface dans un dossier qui peut contenir autre chose."""
        assert to_erase(["mes-documents", "greffier-2026-09-01_12h00"]) == []

    def test_le_compte_garde_une_semaine_de_travail(self):
        assert 3 <= KEPT <= 14
