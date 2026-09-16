"""Writing the minutes again alone, from a master file already on disk."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.application import render
from greffier.application.render import regenerate_minutes, render_transcript
from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span, SpeakerTurn, Utterance


def a_meeting(**overrides) -> StoredMeeting:
    defects = dict(
        identifier="2026-08-24_reunion",
        audio=Path("/tmp/r.wav"),
        processed_at=datetime.now(UTC),
        duration=100.0,
        utterances=[Utterance(Span(0, 40), "bonjour à tous", "1"),
                   Utterance(Span(60, 95), "au revoir", "2")],
        turns=[SpeakerTurn(Span(0, 40), "1"), SpeakerTurn(Span(60, 95), "2")],
        names={"1": "Josiane"},
        propositions={},
        warnings=[],
        hardware_events=[],
    )
    defects.update(overrides)
    return StoredMeeting(**defects)


class FakeWriter:
    def __init__(self) -> None:
        self.received: str | None = None

    def write_up(self, transcription: str) -> str:
        self.received = transcription
        return "# Compte rendu\n\nTout va bien."


class TestRenderingTheTranscription:
    def test_it_works_straight_off_a_meeting_read_back(self) -> None:
        """`StoredMeeting` has to satisfy the same protocol as the outcome of a run, with
        no conversion: that is what allows the writing to be replayed without going
        through a full processing again.
        """
        text = render_transcript(a_meeting())
        assert "[Josiane]" in text
        assert "[Personne 2]" in text


class TestWritingTheMinutesAgain:
    def test_the_writer_receives_the_names_as_they_stand(self) -> None:
        meeting = a_meeting(names={"1": "Josiane", "2": "Marc"})
        writer = FakeWriter()
        regenerate_minutes(meeting, writer)
        assert "[Josiane]" in writer.received
        assert "[Marc]" in writer.received

    def test_the_text_returned_is_the_writer_s(self) -> None:
        assert (
            regenerate_minutes(a_meeting(), FakeWriter())
            == "# Compte rendu\n\nTout va bien."
        )

    def test_a_single_take_survives_the_rewrite(self) -> None:
        """Regenerating must not lose how the names were given in the first place."""
        from greffier.application.render import ATTRIBUTION_BY_VOICE_LINE

        writer = FakeWriter()
        regenerate_minutes(a_meeting(one_take=True), writer)
        assert ATTRIBUTION_BY_VOICE_LINE in writer.received

    def test_two_channels_say_nothing_about_the_take(self) -> None:
        from greffier.application.render import ATTRIBUTION_BY_VOICE_LINE

        writer = FakeWriter()
        regenerate_minutes(a_meeting(), writer)
        assert ATTRIBUTION_BY_VOICE_LINE not in writer.received

    def test_the_hardware_events_survive_the_rewrite(self) -> None:
        """The defect aimed at: regenerating must not make the minutes less
        reliable than the original by losing what the hardware watch knew."""
        meeting = a_meeting(hardware_events=["casque branché à 12:03"])
        writer = FakeWriter()
        regenerate_minutes(meeting, writer)
        assert "casque branché à 12:03" in writer.received


class TestTheInstructionsGivenDuringTheMeeting:
    """What was said to the tool during the meeting has to reach the writer.

    The defect, reported word for word: "I had said in the tool's chat that there
    was no Sophie in the meeting… and in the chat I had given it instructions for
    the minutes, and none of that was taken into account in the minutes". The
    seventeen messages were kept on disk and read by nobody.
    """

    def test_every_instruction_is_dictated(self):
        header = render.instructions_header([
            "Il n'y a pas de sophie dans la réunion",
            "Pascal n'a pas dit booting, mais blue team",
        ])
        assert "Il n'y a pas de sophie" in header
        assert "blue team" in header

    def test_the_header_says_they_win(self):
        """Without it the writer arbitrates between the instruction and the transcription."""
        header = render.instructions_header(["Il n'y a pas de sophie"])
        assert "l'emportent" in header
        assert "Applique-les" in header

    def test_with_no_instruction_there_is_no_header(self):
        assert render.instructions_header([]) == ""

    def test_the_header_ends_cleanly(self):
        """It is stuck to the others: without the blank line, two blocks touch."""
        assert render.instructions_header(["une"]).endswith("\n\n")


class TestThePassagesWorthHearingAgain:
    def test_each_voice_gets_its_share_of_the_target_length(self):
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 60), "1"), SpeakerTurn(Span(60, 120), "2")],
        )
        passages = render.notable_passages(meeting, target_length=40.0, minimum_length=8.0)
        assert [(p.start, p.end) for p in passages] == [(0, 20), (60, 80)]

    def test_a_voice_too_short_for_the_minimum_is_left_out(self):
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 100), "1"), SpeakerTurn(Span(100, 103), "2")],
        )
        passages = render.notable_passages(meeting, target_length=60.0, minimum_length=8.0)
        assert {p.start for p in passages} == {0}

    def test_the_longest_turns_come_first_and_the_result_is_in_order(self):
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 10), "1"), SpeakerTurn(Span(50, 90), "1"),
                   SpeakerTurn(Span(20, 25), "1")],
        )
        passages = render.notable_passages(meeting, target_length=45.0, minimum_length=8.0)
        # The forty-second turn first, then the rest of the quota, never
        # below the minimum: eight seconds of the ten-second turn.
        assert [(p.start, p.end) for p in passages] == [(0, 8.0), (50, 90)]

    def test_assembling_nothing_is_refused(self, tmp_path):
        import pytest

        with pytest.raises(ValueError, match="aucun passage"):
            render.assemble(tmp_path / "r.wav", [], tmp_path / "montage.m4a")


class TestWhatIsNotPronounced:
    def test_tables_headings_and_links_are_stripped(self):
        text = ("# Compte rendu\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                "Voir [le ticket](https://x/1) **vite**.\n\n\n\nFin.")
        assert render._without_markup(text) == "Compte rendu\n\nVoir le ticket vite.\n\nFin."

    def test_without_a_synthesiser_reading_aloud_says_so(self, tmp_path, monkeypatch):
        import pytest

        monkeypatch.setattr(render, "SYSTEM", "Linux")
        monkeypatch.setattr(render.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="espeak-ng"):
            render.speak_aloud("Bonjour.", tmp_path / "lecture.m4a")

    def test_with_espeak_the_wav_is_written_where_asked(self, tmp_path, monkeypatch):
        monkeypatch.setattr(render, "SYSTEM", "Linux")
        monkeypatch.setattr(render.shutil, "which", lambda name: "/usr/bin/espeak-ng")
        calls = []
        monkeypatch.setattr(render.subprocess, "run", lambda command, **k: calls.append(command))
        written = render.speak_aloud("# Titre\n\nBonjour.", tmp_path / "lecture.m4a")
        assert written == tmp_path / "lecture.wav"
        assert calls[0][-1] == "Titre\n\nBonjour."


class FakeExtractor:
    """Gives every voice the same signature, so that stitching joins them all."""

    def __init__(self, vectors):
        self.vectors = vectors

    def extract_spans(self, audio, spans):
        return [self.vectors[span.start] for span in spans if span.start in self.vectors]


class TestReviewingTheVoices:
    def _voiceprint(self, *vector):
        from greffier.domain.models import Voiceprint

        return Voiceprint(vector=vector, source_duration=20.0)

    def test_two_voices_with_one_signature_become_one_and_the_name_follows(self):
        same = self._voiceprint(1.0, 0.0, 0.0)
        meeting = a_meeting(
            utterances=[Utterance(Span(0, 40), "bonjour", "1"),
                        Utterance(Span(60, 95), "suite", "2")],
            turns=[SpeakerTurn(Span(0, 40), "1"), SpeakerTurn(Span(60, 95), "2")],
            names={"1": "Josiane"},
        )
        earlier, later = render.review_voices(meeting, FakeExtractor({0: same, 60: same}))
        assert (earlier, later) == (2, 1)
        assert len(meeting.names) == 1
        assert set(meeting.names.values()) == {"Josiane"}
        assert {u.voice for u in meeting.utterances} == set(meeting.names)

    def test_two_different_signatures_stay_two_voices(self):
        meeting = a_meeting(names={"1": "Josiane"})
        one, other = self._voiceprint(1.0, 0.0, 0.0), self._voiceprint(0.0, 1.0, 0.0)
        earlier, later = render.review_voices(meeting, FakeExtractor({0: one, 60: other}))
        assert (earlier, later) == (2, 2)
        assert meeting.names == {"1": "Josiane"}

    def test_the_bank_is_asked_again_about_a_voice_without_a_name(self):
        from greffier.domain.models import Person

        one, other = self._voiceprint(1.0, 0.0, 0.0), self._voiceprint(0.0, 1.0, 0.0)
        meeting = a_meeting(names={"1": "Josiane"})

        class Bank:
            def people(self):
                return [Person(name="Marc", voiceprints=[other]),
                        Person(name="Josiane", voiceprints=[one])]

        render.review_voices(meeting, FakeExtractor({0: one, 60: other}), Bank())
        assert meeting.names == {"1": "Josiane", "2": "Marc"}

    def test_two_names_on_one_stitched_voice_keep_the_longer_and_say_the_other(self):
        """The dropped name used to go into a proposition the next line threw
        away: a person vanished from the meeting without a word."""
        same = self._voiceprint(1.0, 0.0, 0.0)
        meeting = a_meeting(
            turns=[SpeakerTurn(Span(0, 40), "1"), SpeakerTurn(Span(60, 95), "2")],
            names={"1": "Josiane", "2": "Marc"},
        )
        render.review_voices(meeting, FakeExtractor({0: same, 60: same}))
        assert list(meeting.names.values()) == ["Josiane"]
        assert meeting.propositions == {}
        assert any("le nom Marc a été écarté" in w for w in meeting.warnings), meeting.warnings
