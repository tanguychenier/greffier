"""Telling the assistant's own voice from the room's.

What it says comes back in through the capture of everybody else's sound, and
the separation counts it as a participant. Reported in use: « ça détectait mal
les voix et en rajoutait à chaque fois » -- one of them was Lucie answering.
"""

from __future__ import annotations

from dataclasses import dataclass

from greffier.domain.her_voice import is_hers, voices_of


@dataclass
class Span:
    start: float
    end: float


@dataclass
class Turn:
    voice: str
    span: Span


def _tour(voice: str, start: float, end: float) -> Turn:
    return Turn(voice=voice, span=Span(start, end))


class TestOnePassage:
    def test_said_inside_one_of_her_intervals_is_hers(self):
        assert is_hers(10.0, 14.0, [(9.5, 15.0)])

    def test_said_elsewhere_is_not(self):
        assert not is_hers(30.0, 34.0, [(9.5, 15.0)])

    def test_a_sentence_merely_overlapping_her_end_belongs_to_the_room(self):
        """Giving it to her would take a participant's words away."""
        assert not is_hers(14.0, 20.0, [(9.5, 15.0)])

    def test_a_syllable_running_over_is_still_hers(self):
        """Her end is estimated from the length of the text, never measured."""
        assert is_hers(10.0, 15.2, [(10.0, 15.0)])

    def test_an_empty_passage_is_nobody(self):
        assert not is_hers(10.0, 10.0, [(0.0, 100.0)])

    def test_with_no_interval_nothing_is_hers(self):
        assert not is_hers(10.0, 14.0, [])


class TestAWholeVoice:
    def test_a_voice_that_is_her_throughout_is_named(self):
        tours = [_tour("v3", 10.0, 14.0), _tour("v3", 40.0, 44.0)]
        assert voices_of(tours, [(9.5, 15.0), (39.5, 45.0)]) == {"v3"}

    def test_a_participant_who_once_talked_over_her_keeps_their_voice(self):
        """Judged on the whole of a voice: one overlap is not an identity."""
        tours = [_tour("v1", 10.0, 14.0)] + [
            _tour("v1", depart, depart + 10.0) for depart in (20.0, 40.0, 60.0)
        ]
        assert voices_of(tours, [(9.5, 15.0)]) == set()

    def test_the_room_is_left_alone(self):
        tours = [_tour("v1", 0.0, 8.0), _tour("v2", 20.0, 28.0)]
        assert voices_of(tours, [(9.5, 15.0)]) == set()

    def test_no_turns_no_voices(self):
        assert voices_of([], [(0.0, 10.0)]) == set()
