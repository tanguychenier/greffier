"""The voice bank on disk, and the master file of a meeting."""

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
        """File systems do not normalise accents the same way."""
        assert _file_at("Rémi Kaës") == _file_at("Remi Kaes")

    def test_an_unusual_name_still_gives_a_file(self):
        """And a file that belongs to it alone.

        This test used to expect "sans-nom", which was the defect itself: every name
        with no ASCII letter returned that value, so the same file, so one person for
        several. The intention held, the assertion betrayed it.
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
        """They are what lets a passage be quoted and found again."""
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
        """Better to refuse than to misread a file from a future version.

        The number is read from the module and not written in: the previous version
        looked for `"format": 1` in the text, so moving to format 2 did not break the
        test. It replaced nothing any more and checked that a valid file raises, which
        it does not.
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
        """Format 1 did not carry the clock times: it stays readable.

        The meetings already on disk do not have to be processed again for the tool to
        still be able to open them.
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
        """Needed to write the minutes again later without losing what the hardware
        watch had seen.
        """
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting(
            hardware_events=["casque branché à 12:03"]
        ))
        relue = magasin.read("2026-08-24_reunion")
        assert relue.hardware_events == ["casque branché à 12:03"]

    def test_a_master_file_with_no_hardware_events_reads_back(self, tmp_path):
        """A master file written before this field was added has no such key: it must
        read back empty, not crash.
        """
        magasin = FileStore(tmp_path)
        magasin.record(a_meeting())
        path = tmp_path / "2026-08-24_reunion.json"
        content = json.loads(path.read_text())
        del content["evenements_materiel"]
        path.write_text(json.dumps(content))
        assert magasin.read("2026-08-24_reunion").hardware_events == []


class TestNonLatinNames:
    """Two people must stay two people.

    Reducing to ASCII has no letter to keep from a Cyrillic, Greek, Arabic or
    ideographic name. Falling back on "sans-nom" filed them all in the same
    voiceprint file: that is not a display matter, it is a merge of data, in the
    very file whose job is to keep them apart. Reachable today by typing a name by
    hand in the Voices tab.
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
        """The merge was silent: two voices in a single folder."""
        bank.record("Δημήτρης", voice(1.0, 0.0))
        bank.record("محمد", voice(0.0, 1.0))

        assert all(len(p.voiceprints) == 1 for p in bank.people())

    def test_a_latin_name_keeps_a_readable_file(self, bank):
        """The fix must not make unreadable the names that were fine."""
        bank.record("Josiane", voice(1.0, 0.0))

        assert (bank.folder / "josiane.json").is_file()


class TestRepairingABank:
    """Correcting at the grain of the voiceprint, not of the person."""

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
        """An entry with no voiceprint recognises nothing and clutters the list."""
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
    """The gesture that was missing: undoing what one meeting poured in."""

    def test_the_voiceprints_of_a_meeting_leave_everywhere(self, tmp_path):
        """A badly attributed meeting pours under several names at once.

        On this machine it took reading the durations, thirteen and thirty-one
        minutes, to understand that two voiceprints of "Pascal" came from a meeting he
        was not in.
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
