"""Reconstruire une réunion depuis le fil du direct, faute de traitement.

Le 2026-09-09, une réunion n'a jamais été finalisée : le fil existait, mais
rien ne savait le lire. La différence que ces tests protègent est celle entre
approximatif et perdu.
"""

from pathlib import Path

from greffier.application.recover import WARNING, depuis_le_fil
from greffier.domain.models import Span, SpeakerTurn


def turn(number: int, start: float, end: float, text: str, voice: str) -> dict:
    return {"genre": "tour", "numero": number, "debut": start, "fin": end,
            "texte": text, "voix": voice, "nom": None,
            "certitude": "inconnue", "rang": 1}


THREAD = [
    {"genre": "etat", "message": "Transcription en direct active.", "actif": True},
    turn(1, 0.0, 5.0, "Bonjour à tous.", "v1"),
    turn(2, 5.0, 11.0, "On commence par la recette.", "v1"),
    turn(3, 12.0, 18.0, "Elle est décalée à jeudi.", "v2"),
]


class TestRebuildingAMeeting:
    def test_the_spoken_lines_become_utterances(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert [r.text for r in meeting.utterances] == [
            "Bonjour à tous.", "On commence par la recette.", "Elle est décalée à jeudi."
        ]

    def test_the_voices_are_kept(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert {t.voice for t in meeting.turns} == {"v1", "v2"}

    def test_the_length_comes_from_the_last_turn(self):
        assert depuis_le_fil("2026-09-09_10h05_reunion", THREAD).duration == 18.0

    def test_the_date_comes_from_the_identifier(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert meeting.started_at is not None
        assert (meeting.started_at.hour, meeting.started_at.minute) == (10, 5)

    def test_the_lines_with_no_speech_are_dropped(self):
        meeting = depuis_le_fil("x", [{"genre": "etat", "message": "actif"}])
        assert meeting.utterances == []

    def test_an_empty_text_is_not_an_utterance(self):
        meeting = depuis_le_fil("x", [turn(1, 0.0, 2.0, "   ", "v1")])
        assert meeting.utterances == []

    def test_the_audio_is_taken_back_when_it_exists(self):
        meeting = depuis_le_fil("x", THREAD, audio=Path("/tmp/x.wav"))
        assert meeting.audio == Path("/tmp/x.wav")


class TestBeingHonestAboutIt:
    """Une transcription de moindre qualité ne doit pas passer pour ordinaire."""

    def test_the_meeting_carries_its_warning(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert meeting.warnings == [WARNING]

    def test_the_warning_says_what_is_worse_about_it(self):
        aplati = " ".join(WARNING.split())
        assert "modèle rapide" in aplati
        assert "approximative" in aplati

    def test_it_also_says_what_would_be_better(self):
        assert "Retraiter" in WARNING


class TestStitchingAfterTheMeeting:
    """Le direct découpe par tranches : une minute de parole fait six tours."""

    def test_the_consecutive_turns_of_one_voice_stitch_together(self):
        from greffier.application.recover import join_spans

        turns = [
            SpeakerTurn(Span(0, 10), "v1"),
            SpeakerTurn(Span(10, 20), "v1"),
            SpeakerTurn(Span(20, 30), "v2"),
        ]
        recolles = join_spans(turns)
        assert len(recolles) == 2
        assert recolles[0].span.end == 20

    def test_a_change_of_voice_cuts(self):
        from greffier.application.recover import join_spans

        turns = [SpeakerTurn(Span(0, 10), "v1"),
                 SpeakerTurn(Span(10, 20), "v2")]
        assert len(join_spans(turns)) == 2

    def test_a_gap_does_not_stitch(self):
        from greffier.application.recover import join_spans

        turns = [SpeakerTurn(Span(0, 10), "v1"),
                 SpeakerTurn(Span(60, 70), "v1")]
        assert len(join_spans(turns)) == 2

    def test_an_empty_list_does_not_raise(self):
        from greffier.application.recover import join_spans

        assert join_spans([]) == []
