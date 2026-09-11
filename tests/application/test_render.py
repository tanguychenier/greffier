"""Régénérer la rédaction seule, depuis un fichier maître déjà écrit."""

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
        """`ReunionEnregistree` doit satisfaire le même protocole que
        `Resultat`, sans conversion : c'est ce qui permet de rejouer la
        rédaction sans repasser par un traitement complet."""
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
    """Ce qu'on a dit à l'outil pendant la réunion doit parvenir au rédacteur.

    Le défaut, rapporté mot pour mot : « j'avais pourtant dit dans le chat de
    l'outil qu'on avait pas de Sophie dans la réunion... et dans le chat je lui
    avais donné des instructions pour le compte rendu, cela n'a pas été pris en
    compte dans le compte rendu ». Les dix-sept messages étaient gardés sur le
    disque et lus par personne.
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
