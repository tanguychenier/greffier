"""Writing the minutes again alone, from a master file already on disk."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.application import render
from greffier.application.render import regenerate_minutes, render_transcript
from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span, SpeakerTurn, Utterance


def a_meeting(**overrides) -> StoredMeeting:
    defauts = dict(
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
    defauts.update(overrides)
    return StoredMeeting(**defauts)


class FakeWriter:
    def __init__(self) -> None:
        self.recu: str | None = None

    def write_up(self, transcription: str) -> str:
        self.recu = transcription
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
        assert "[Josiane]" in writer.recu
        assert "[Marc]" in writer.recu

    def test_the_text_returned_is_the_writer_s(self) -> None:
        assert (
            regenerate_minutes(a_meeting(), FakeWriter())
            == "# Compte rendu\n\nTout va bien."
        )

    def test_the_hardware_events_survive_the_rewrite(self) -> None:
        """Le défaut visé : régénérer ne doit pas rendre le compte rendu moins
        fiable que l'original en perdant ce que la veille du matériel savait."""
        meeting = a_meeting(hardware_events=["casque branché à 12:03"])
        writer = FakeWriter()
        regenerate_minutes(meeting, writer)
        assert "casque branché à 12:03" in writer.recu


class TestTheInstructionsGivenDuringTheMeeting:
    """What was said to the tool during the meeting has to reach the writer.

    The defect, reported word for word: "I had said in the tool's chat that there
    was no Sophie in the meeting… and in the chat I had given it instructions for
    the minutes, and none of that was taken into account in the minutes". The
    seventeen messages were kept on disk and read by nobody.
    """

    def test_every_instruction_is_dictated(self):
        entete = render.instructions_header([
            "Il n'y a pas de sophie dans la réunion",
            "Pascal n'a pas dit booting, mais blue team",
        ])
        assert "Il n'y a pas de sophie" in entete
        assert "blue team" in entete

    def test_the_header_says_they_win(self):
        """Sans cela le rédacteur arbitre entre la consigne et la transcription."""
        entete = render.instructions_header(["Il n'y a pas de sophie"])
        assert "l'emportent" in entete
        assert "Applique-les" in entete

    def test_with_no_instruction_there_is_no_header(self):
        assert render.instructions_header([]) == ""

    def test_the_header_ends_cleanly(self):
        """Il est collé aux autres : sans la ligne vide, deux blocs se touchent."""
        assert render.instructions_header(["une"]).endswith("\n\n")
