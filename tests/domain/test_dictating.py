"""When a spoken sentence is over.

Holding a button down says it, and makes the person hold a mouse while they read
the document they are asking about -- which is what they are doing when they
prepare a meeting. So silence ends the take.
"""

from __future__ import annotations

from greffier.domain.dictating import SILENCE_DB, Take


def _parle(prise: Take, secondes: float, pas: float = 0.2) -> None:
    for _ in range(int(secondes / pas)):
        prise.heard(-20.0, pas)


def _se_tait(prise: Take, secondes: float, pas: float = 0.2) -> None:
    for _ in range(int(secondes / pas)):
        prise.heard(-60.0, pas)


class TestWhenItEnds:
    def test_speech_then_silence_ends_it(self):
        prise = Take()
        _parle(prise, 2.0)
        assert not prise.over
        _se_tait(prise, 1.6)
        assert prise.over

    def test_a_pause_inside_a_sentence_does_not(self):
        """French carries pauses of nearly a second between two words."""
        prise = Take()
        _parle(prise, 2.0)
        _se_tait(prise, 0.8)
        assert not prise.over
        _parle(prise, 1.0)
        assert not prise.over

    def test_somebody_who_says_nothing_is_not_finished(self):
        """They are thinking, or the microphone is the wrong one."""
        prise = Take()
        _se_tait(prise, 10.0)
        assert not prise.over

    def test_a_first_word_cut_by_its_own_breath_is_not_the_end(self):
        prise = Take()
        _parle(prise, 0.4)
        _se_tait(prise, 2.0)
        assert not prise.over, "moins d'une seconde de prise : rien à transcrire"

    def test_the_floor_is_below_speech_and_above_a_room(self):
        """Measured on the meters: speech -30 to -12, a quiet room -60 to -50."""
        assert -50 < SILENCE_DB < -30
