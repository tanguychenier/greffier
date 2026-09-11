"""La banque de voix sur le disque, et le fichier maître d'une réunion."""

import json
from datetime import UTC, datetime

import pytest

from greffier.adapters.store_files import FORMAT, FileStore, StoredMeeting
from greffier.adapters.voice_bank_files import FileVoiceBank, _file_at
from greffier.domain.models import Span, SpeakerTurn, Utterance
from greffier.domain.voiceprints import normalise, recognise


def voice(*composantes, duration=10.0):
    return normalise(composantes, source_duration=duration)


@pytest.fixture
def bank(tmp_path):
    return FileVoiceBank(tmp_path / "banque-de-voix")


class TestTheVoiceBank:
    def test_a_recorded_voice_is_read_back(self, bank):
        bank.record("Josiane", voice(1.0, 0.0, 0.0))
        people = bank.people()
        assert [p.name for p in people] == ["Josiane"]
        assert len(people[0].voiceprints) == 1

    def test_recognition_survives_the_round_trip_to_disk(self, bank):
        """Le vrai but : reconnue d'une réunion à l'autre."""
        bank.record("Josiane", voice(1.0, 0.02, 0.0))
        bank.record("Marc", voice(0.0, 0.0, 1.0))
        found = recognise(voice(0.99, 0.05, 0.0), bank.people())
        assert found is not None and found.name == "Josiane"

    def test_the_voiceprints_pile_up_for_one_person(self, bank):
        for i in range(3):
            bank.record("Josiane", voice(1.0, i / 10, 0.0))
        assert len(bank.find("Josiane").voiceprints) == 3

    def test_what_piles_up_stays_bounded(self, tmp_path):
        bank = FileVoiceBank(tmp_path / "b", maximum=2)
        for i in range(6):
            bank.record("Josiane", voice(1.0, 0.0, duration=float(i)))
        assert len(bank.find("Josiane").voiceprints) == 2

    def test_accents_do_not_create_two_people(self):
        """Les systèmes de fichiers ne normalisent pas les accents pareil."""
        assert _file_at("Rémi Kaës") == _file_at("Remi Kaes")

    def test_an_unusual_name_still_gives_a_file(self):
        """Et un fichier qui n'appartient qu'à lui.

        Ce test attendait « sans-nom », qui était le défaut même : tous les noms
        sans lettre ASCII rendaient cette valeur, donc le même fichier, donc une
        seule personne pour plusieurs. L'intention tenait, l'assertion la
        trahissait.
        """
        assert _file_at("???")
        assert _file_at("???") != _file_at("!!!")

    def test_renaming_keeps_the_voiceprints(self, bank):
        bank.record("Josianne", voice(1.0, 0.0))
        bank.rename("Josianne", "Josiane")
        assert bank.find("Josianne") is None
        assert len(bank.find("Josiane").voiceprints) == 1

    def test_joining_brings_two_entries_together(self, bank):
        bank.record("Josiane", voice(1.0, 0.0))
        bank.record("Josiane B", voice(0.9, 0.1))
        fusionnee = bank.join("Josiane", "Josiane B")
        assert len(fusionnee.voiceprints) == 2
        assert bank.find("Josiane B") is None

    def test_forgetting_really_deletes(self, bank):
        """Donnée biométrique : la suppression doit être simple et complète."""
        bank.record("Josiane", voice(1.0, 0.0))
        assert bank.forget("Josiane") is True
        assert bank.people() == []
        assert bank.forget("Josiane") is False

    def test_a_damaged_file_does_not_stop_the_others_being_read(self, bank):
        bank.record("Josiane", voice(1.0, 0.0))
        (bank.folder / "casse.json").write_text("{ pas du json", encoding="utf-8")
        assert [p.name for p in bank.people()] == ["Josiane"]

    def test_a_missing_bank_is_not_an_error(self, tmp_path):
        assert FileVoiceBank(tmp_path / "jamais-creee").people() == []


def a_meeting(**overrides):
    defauts = dict(
        identifier="2026-08-24_reunion",
        audio=__import__("pathlib").Path("/tmp/r.wav"),
        processed_at=datetime.now(UTC),
        duration=100.0,
        utterances=[Utterance(Span(0, 40), "bonjour à tous", "1"),
                   Utterance(Span(60, 95), "au revoir", "2")],
        turns=[SpeakerTurn(Span(0, 40), "1"), SpeakerTurn(Span(60, 95), "2")],
        names={"1": "Josiane"},
        propositions={"2": "Marc"},
        warnings=[],
    )
    defauts.update(overrides)
    return StoredMeeting(**defauts)


class TestTheMasterFile:
    def test_what_is_written_is_read_back_identical(self, tmp_path):
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting())
        relue = magasin.read("2026-08-24_reunion")
        assert relue.names == {"1": "Josiane"}
        assert relue.propositions == {"2": "Marc"}
        assert [r.text for r in relue.utterances] == ["bonjour à tous", "au revoir"]
        assert relue.utterances[0].span.end == 40

    def test_the_timestamps_survive(self, tmp_path):
        """Ils permettent de citer un passage et d'y revenir."""
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting())
        assert magasin.read("2026-08-24_reunion").turns[1].span.start == 60

    def test_the_coverage_shows_what_is_missing(self):
        """75 s de texte sur 100 s d'audio : un quart n'a pas été transcrit."""
        assert a_meeting().coverage == pytest.approx(0.75)

    def test_the_holes_are_listed(self):
        gaps = a_meeting().gaps(minimum=5.0)
        assert [(t.start, t.end) for t in gaps] == [(40.0, 60.0), (95.0, 100.0)]

    def test_a_small_silence_is_not_a_hole(self):
        assert a_meeting().gaps(minimum=30.0) == []

    def test_an_unknown_meeting_says_so_plainly(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="inconnue"):
            FileStore(tmp_path).read("jamais-vue")

    def test_a_newer_format_is_refused(self, tmp_path):
        """Mieux vaut refuser que lire de travers un fichier d'une version future.

        Le numéro est lu depuis le module et non écrit en dur : la version
        précédente cherchait « "format": 1 » dans le texte, si bien que passer
        au format 2 ne cassait pas le test — il ne remplaçait plus rien et
        vérifiait qu'un fichier valide lève une erreur, ce qu'il ne fait pas.
        """
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting())
        path = tmp_path / "2026-08-24_reunion.json"
        content = json.loads(path.read_text(encoding="utf-8"))
        content["format"] = FORMAT + 1
        path.write_text(json.dumps(content), encoding="utf-8")
        with pytest.raises(ValueError, match="plus récente"):
            magasin.read("2026-08-24_reunion")

    def test_a_file_without_the_clock_times_reads_back(self, tmp_path):
        """Le format 1 ne portait pas les heures d'horloge : il reste lisible.

        Les réunions déjà sur le disque n'ont pas à être retraitées pour que
        l'outil sache encore les ouvrir.
        """
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting())
        path = tmp_path / "2026-08-24_reunion.json"
        content = json.loads(path.read_text(encoding="utf-8"))
        content["format"] = 1
        del content["commencee_le"]
        del content["terminee_le"]
        path.write_text(json.dumps(content), encoding="utf-8")
        relue = magasin.read("2026-08-24_reunion")
        assert relue.started_at is None
        assert relue.ended_at is None
        assert relue.utterances, "le reste du fichier se lit normalement"

    def test_the_most_recent_ones_first(self, tmp_path):
        magasin = FileStore(tmp_path)
        for identifier in ("2026-08-01_a", "2026-08-24_b", "2026-08-12_c"):
            magasin.record(a_meeting(identifier=identifier))
        assert magasin.lister()[0] == "2026-08-24_b"

    def test_the_hardware_events_survive(self, tmp_path):
        """Nécessaire pour régénérer la rédaction plus tard sans perdre ce que
        la veille du matériel avait constaté."""
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting(
            hardware_events=["casque branché à 12:03"]
        ))
        relue = magasin.read("2026-08-24_reunion")
        assert relue.hardware_events == ["casque branché à 12:03"]

    def test_a_master_file_with_no_hardware_events_reads_back(self, tmp_path):
        """Un fichier maître écrit avant l'ajout de ce champ n'a pas la clé :
        elle doit se relire vide, pas planter."""
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting())
        path = tmp_path / "2026-08-24_reunion.json"
        content = json.loads(path.read_text())
        del content["evenements_materiel"]
        path.write_text(json.dumps(content))
        assert magasin.read("2026-08-24_reunion").hardware_events == []


class TestNonLatinNames:
    """Deux personnes doivent rester deux personnes.

    La réduction en ASCII n'a aucune lettre à garder d'un nom cyrillique, grec,
    arabe ou idéographique. Le repli sur « sans-nom » les rangeait toutes dans
    le même fichier d'empreintes : ce n'est pas de l'affichage, c'est une fusion
    de données, dans le fichier même qui doit les tenir séparées. Atteignable
    dès aujourd'hui par un nom saisi à la main dans l'onglet Voix.
    """

    def test_two_non_latin_names_stay_two_files(self, bank):
        bank.record("Дмитрий", voice(1.0, 0.0))
        bank.record("Ольга", voice(0.0, 1.0))

        assert len(list(bank.folder.glob("*.json"))) == 2

    def test_each_one_reads_back_under_its_own_name(self, bank):
        bank.record("田中", voice(1.0, 0.0))
        bank.record("佐藤", voice(0.0, 1.0))

        assert {p.name for p in bank.people()} == {"田中", "佐藤"}

    def test_their_voiceprints_do_not_mix(self, bank):
        """La fusion était silencieuse : deux voix dans un seul dossier."""
        bank.record("Δημήτρης", voice(1.0, 0.0))
        bank.record("محمد", voice(0.0, 1.0))

        assert all(len(p.voiceprints) == 1 for p in bank.people())

    def test_a_latin_name_keeps_a_readable_file(self, bank):
        """La correction ne doit pas rendre illisibles les noms qui allaient bien."""
        bank.record("Josiane", voice(1.0, 0.0))

        assert (bank.folder / "josiane.json").is_file()


class TestRepairingABank:
    """Corriger au grain de l'empreinte, et non de la personne."""

    def test_one_voiceprint_can_go_without_losing_the_others(self, tmp_path):
        """Effacer quelqu'un pour une empreinte fautive perd tout le reste.

        Ce qui décide de la reconnaissance est l'empreinte : c'est donc à ce
        grain qu'on doit pouvoir corriger.
        """
        bank = FileVoiceBank(tmp_path)
        for vector in ([1.0, 0.0], [0.0, 1.0], [0.5, 0.5]):
            bank.record("Pascal", normalise(vector, source_duration=10.0))
        assert bank.remove_voiceprints("Pascal", [1]) == 1
        remaining = bank.find("Pascal")
        assert remaining is not None and len(remaining.voiceprints) == 2

    def test_removing_everything_deletes_the_person(self, tmp_path):
        """Une entrée sans empreinte ne reconnaît rien et encombre la liste."""
        bank = FileVoiceBank(tmp_path)
        bank.record("Pascal", normalise([1.0, 0.0], source_duration=10.0))
        assert bank.remove_voiceprints("Pascal", [0]) == 1
        assert bank.find("Pascal") is None

    def test_an_index_out_of_range_breaks_nothing(self, tmp_path):
        bank = FileVoiceBank(tmp_path)
        bank.record("Pascal", normalise([1.0, 0.0], source_duration=10.0))
        assert bank.remove_voiceprints("Pascal", [7]) == 0
        assert bank.find("Pascal") is not None

    def test_an_unknown_person_does_not_raise(self, tmp_path):
        assert FileVoiceBank(tmp_path).remove_voiceprints("Absent", [0]) == 0


class TestForgettingAMeetingEverywhere:
    """Le geste qui manquait : défaire ce qu'une réunion a versé."""

    def test_the_voiceprints_of_a_meeting_leave_everywhere(self, tmp_path):
        """Une réunion mal attribuée verse sous plusieurs noms d'un coup.

        Sur ce poste, il a fallu lire les durées — treize et trente et une
        minutes — pour comprendre que deux empreintes de « Pascal » venaient
        d'une réunion où il n'était pas.
        """
        from dataclasses import replace

        bank = FileVoiceBank(tmp_path)
        bonne = normalise([1.0, 0.0], source_duration=10.0)
        fautive = replace(normalise([0.0, 1.0], source_duration=900.0),
                          origin="2026-09-09_reunion")
        bank.record("Pascal", bonne)
        bank.record("Pascal", fautive)
        bank.record("Kilian", fautive)

        retires = bank.forget_a_meeting("2026-09-09_reunion")

        assert retires == {"Pascal": 1, "Kilian": 1}
        pascal = bank.find("Pascal")
        assert pascal is not None and len(pascal.voiceprints) == 1
        # Kilian n'avait que celle-là : il disparaît plutôt que de rester vide.
        assert bank.find("Kilian") is None

    def test_an_unknown_meeting_touches_nothing(self, tmp_path):
        bank = FileVoiceBank(tmp_path)
        bank.record("Pascal", normalise([1.0, 0.0], source_duration=10.0))
        assert bank.forget_a_meeting("jamais-tenue") == {}
        assert bank.find("Pascal") is not None

    def test_where_it_came_from_survives_being_written(self, tmp_path):
        """Sans persistance, la trace ne servirait qu'au processus qui l'a posée."""
        from dataclasses import replace

        bank = FileVoiceBank(tmp_path)
        bank.record("Pascal", replace(
            normalise([1.0, 0.0], source_duration=10.0), origin="2026-09-09_reunion"))
        relue = FileVoiceBank(tmp_path).find("Pascal")
        assert relue is not None
        assert relue.voiceprints[0].origin == "2026-09-09_reunion"
