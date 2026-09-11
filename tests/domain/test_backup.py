"""Ce qu'une sauvegarde emporte, et ce qu'elle laisse."""

from datetime import datetime

from greffier.domain.backup import (
    CONTENT,
    ECARTES,
    KEPT,
    BackupName,
    to_erase,
)


class TestWhatIsBackedUp:
    def test_the_voice_bank_comes_first(self):
        """Elle a été construite un nom à la fois : rien ne la refera."""
        assert CONTENT[0] == "banque-de-voix"

    def test_the_audio_is_left_out(self):
        """C'est lui qui rend une sauvegarde impossible : 115 Mo par heure."""
        assert "enregistrements" in ECARTES
        assert "enregistrements" not in CONTENT

    def test_the_models_are_left_out(self):
        assert "modeles" in ECARTES

    def test_every_exclusion_says_why(self):
        """Une sauvegarde qui grossit sans raison connue finit par ne plus se faire."""
        for folder, because in ECARTES.items():
            assert len(because) > 20, folder

    def test_nothing_is_both_taken_and_left_out(self):
        assert not set(CONTENT) & set(ECARTES)

    def test_what_carries_the_work_is_taken(self):
        for essentiel in ("reunions", "comptes-rendus", "transcriptions",
                          "conversations"):
            assert essentiel in CONTENT


class TestTheBackupName:
    def test_the_name_carries_the_date_to_the_minute(self):
        """Deux sauvegardes du même jour doivent pouvoir coexister."""
        name = BackupName(datetime(2026, 9, 9, 14, 5))
        assert str(name) == "greffier-2026-09-09_14h05"

    def test_the_name_reads_back(self):
        when = datetime(2026, 9, 9, 14, 5)
        assert BackupName.read(str(BackupName(when))) == when

    def test_what_is_not_a_backup_is_refused(self):
        assert BackupName.read("mes-documents") is None
        assert BackupName.read("greffier-pas-une-date") is None


class TestKeepingOnlySoMany:
    def names(self, how_many: int) -> list[str]:
        return [str(BackupName(datetime(2026, 9, jour, 12, 0))) for jour in range(1, how_many + 1)]

    def test_under_the_count_nothing_is_deleted(self):
        assert to_erase(self.names(3), kept=7) == []

    def test_the_oldest_ones_go(self):
        a_partir = to_erase(self.names(10), kept=7)
        assert len(a_partir) == 3
        assert "greffier-2026-09-01_12h00" in a_partir
        assert "greffier-2026-09-10_12h00" not in a_partir

    def test_the_most_recent_one_never_goes(self):
        """Une rotation qui peut tout effacer est une purge, pas une rotation."""
        names = self.names(5)
        a_partir = to_erase(names, kept=0)
        assert "greffier-2026-09-05_12h00" not in a_partir
        assert len(a_partir) == 4

    def test_what_is_not_a_backup_is_left_alone(self):
        """On efface dans un dossier qui peut contenir autre chose."""
        assert to_erase(["mes-documents", "greffier-2026-09-01_12h00"]) == []

    def test_the_count_keeps_a_week_of_work(self):
        assert 3 <= KEPT <= 14
