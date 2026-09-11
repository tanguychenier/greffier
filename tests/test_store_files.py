"""The master file: what is kept, and in what order it is found again."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.adapters.store_files import FileStore
from greffier.domain.meeting import StoredMeeting, held_on
from greffier.domain.models import Span, SpeakerTurn, Utterance


def meeting(identifier: str) -> StoredMeeting:
    return StoredMeeting(
        identifier=identifier,
        audio=Path(f"/tmp/{identifier}.wav"),
        processed_at=datetime.now(UTC),
        duration=60.0,
        utterances=[Utterance(Span(0, 5), "Bonjour.")],
        turns=[SpeakerTurn(Span(0, 5), "1")],
        names={},
        propositions={},
        warnings=[],
    )


class TestTheOrderOfTheMeetings:
    """"The last meeting" has to be the last one **held**.

    The sort was reverse alphabetical, which works as long as every identifier
    starts with its date. On 2026-09-09 "fausse-reunion", a rehearsal meeting, came
    before "2026-09-09_10h05_reunion" because "f" comes after "2": `greffier
    rediger` with no argument wrote up the minutes of the wrong meeting, and
    `greffier envoyer` would have sent them.
    """

    def test_dated_meetings_run_newest_to_oldest(self, tmp_path):
        store = FileStore(tmp_path)
        for identifier in ("2026-09-02_17h37_reunion", "2026-09-09_10h05_reunion",
                            "2026-09-09_08h30_reunion"):
            store.record(meeting(identifier))
        assert store.lister() == [
            "2026-09-09_10h05_reunion",
            "2026-09-09_08h30_reunion",
            "2026-09-02_17h37_reunion",
        ]

    def test_an_undated_identifier_does_not_jump_ahead_of_a_dated_one(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("2026-09-09_10h05_reunion"))
        store.record(meeting("fausse-reunion"))
        assert store.lister()[0] == "2026-09-09_10h05_reunion"
        assert "fausse-reunion" in store.lister()

    def test_the_latest_is_the_most_recently_held(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("zzz-essai"))
        store.record(meeting("2026-09-09_10h05_reunion"))
        latest = store.latest()
        assert latest is not None
        assert latest.identifier == "2026-09-09_10h05_reunion"

    def test_with_no_folder_the_list_is_empty(self, tmp_path):
        assert FileStore(tmp_path / "rien").lister() == []


class TestTheTimestampInsideTheIdentifier:
    def test_the_date_and_the_time_are_read(self):
        assert held_on("2026-09-09_10h05_reunion") == (2026, 9, 9, 10, 5)

    def test_a_date_with_no_time_stays_readable(self):
        assert held_on("2026-09-09_reunion") == (2026, 9, 9, 0, 0)

    def test_an_identifier_with_no_date_does_not_lie(self):
        assert held_on("fausse-reunion") is None


class TestASubjectChosenByHand:
    """A subject typed by hand wins over the title of the minutes.

    Asked for in use: the list showed only "2026-09-09_10h05_reunion" as long as no
    minutes existed, and nothing allowed it to be named.
    """

    def test_the_subject_survives_being_written(self, tmp_path):
        store = FileStore(tmp_path)
        gardee = meeting("2026-09-09_10h05_reunion")
        gardee.subject = "Point Oasis"
        store.record(gardee)
        assert store.read("2026-09-09_10h05_reunion").subject == "Point Oasis"

    def test_with_no_subject_the_identifier_names_the_meeting(self):
        assert meeting("2026-09-09_10h05_reunion").caption == "2026-09-09_10h05_reunion"

    def test_with_a_subject_it_is_the_one_that_names(self):
        gardee = meeting("2026-09-09_10h05_reunion")
        gardee.subject = "Point Oasis"
        assert gardee.caption == "Point Oasis"


class TestDeletingAMeeting:
    def test_the_master_file_goes(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("2026-09-09_10h05_reunion"))
        assert store.delete("2026-09-09_10h05_reunion") is True
        assert store.lister() == []

    def test_deleting_what_does_not_exist_says_so(self, tmp_path):
        assert FileStore(tmp_path).delete("jamais-vue") is False


class TestTheRoundTrip:
    def test_what_is_written_reads_back(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("2026-09-09_10h05_reunion"))
        relue = store.read("2026-09-09_10h05_reunion")
        assert relue.utterances[0].text == "Bonjour."
        assert relue.turns[0].voice == "1"


def joined_meeting(identifier: str = "2026-09-10_10h10_reunion") -> StoredMeeting:
    """Une réunion où deux voix ont été réunies sous le même nom."""
    detail = StoredMeeting(
        identifier=identifier,
        audio=Path(f"/tmp/{identifier}.wav"),
        processed_at=datetime.now(UTC),
        duration=60.0,
        utterances=[
            Utterance(Span(0, 5), "on cale la recette jeudi", voice="v1"),
            Utterance(Span(6, 11), "le devis part demain", voice="v2"),
        ],
        turns=[SpeakerTurn(Span(0, 5), "v1"), SpeakerTurn(Span(6, 11), "v2")],
        names={"v1": "Tanguy", "v2": "Pascal"},
        propositions={},
        warnings=[],
    )
    detail.join_into("v2", "v1")
    return detail


class TestSplittingTwoVoicesAfterTheMeeting:
    """Joining two voices could be undone live, and by nothing afterwards.

    The gesture existed on both sides — naming two voices alike joins them, which
    is exactly what is wanted when the tool has cut one person in two — but only
    the live thread knew how to go back.
    """

    def test_the_absorbed_voice_takes_its_turns_back(self):
        detail = joined_meeting()
        assert {t.voice for t in detail.turns} == {"v1"}
        assert detail.split("v1") is not None
        assert {t.voice for t in detail.turns} == {"v1", "v2"}

    def test_it_takes_its_utterances_back(self):
        detail = joined_meeting()
        detail.split("v1")
        par_voix = {u.voice for u in detail.utterances}
        assert par_voix == {"v1", "v2"}

    def test_it_takes_its_name_back(self):
        detail = joined_meeting()
        detail.split("v1")
        assert detail.names == {"v1": "Tanguy", "v2": "Pascal"}

    def test_nothing_to_split_breaks_nothing(self):
        detail = meeting("2026-09-10_11h00_reunion")
        assert detail.split("1") is None
        assert not detail.can_split("1")

    def test_the_join_can_be_asked_about_before_undoing_it(self):
        detail = joined_meeting()
        assert detail.can_split("v1")
        detail.split("v1")
        assert not detail.can_split("v1"), "une fois défaite, plus rien à défaire"

    def test_the_join_survives_being_written(self, tmp_path):
        """Without that, splitting works only while the application stays open."""
        magasin = FileStore(tmp_path)
        magasin.record(joined_meeting())
        relue = magasin.read("2026-09-10_10h10_reunion")
        assert relue.can_split("v1")
        assert relue.split("v1") is not None
        assert {t.voice for t in relue.turns} == {"v1", "v2"}

    def test_a_file_written_before_stays_readable(self, tmp_path):
        """Aucune réunion déjà traitée ne doit devenir illisible."""
        import json

        magasin = FileStore(tmp_path)
        path = magasin.record(meeting("2026-09-09_10h05_reunion"))
        contenu = json.loads(path.read_text(encoding="utf-8"))
        del contenu["fusions"]
        path.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
        relue = magasin.read("2026-09-09_10h05_reunion")
        assert relue.joins == []
        assert not relue.can_split("1")

    def test_two_joins_come_apart_in_reverse_order(self):
        detail = joined_meeting()
        detail.utterances.append(Utterance(Span(12, 17), "et la prod lundi", voice="v3"))
        detail.turns.append(SpeakerTurn(Span(12, 17), "v3"))
        detail.names["v3"] = "Sophie"
        detail.join_into("v3", "v1")
        assert {t.voice for t in detail.turns} == {"v1"}
        detail.split("v1")
        assert "v3" in {t.voice for t in detail.turns}, "la dernière d'abord"
        assert "v2" not in {t.voice for t in detail.turns}
        detail.split("v1")
        assert {t.voice for t in detail.turns} == {"v1", "v2", "v3"}
