"""Saying that a sentence is not sure, and only where it is not."""

from __future__ import annotations

from greffier.domain.doubt import (
    MARK,
    UNSURE_BELOW,
    Doubts,
    count,
    is_unsure,
    said_in_french,
    worth_listening_again,
)
from greffier.domain.models import Span, Utterance


def said(start: float, text: str, confidence: float | None) -> Utterance:
    return Utterance(span=Span(start, start + 2), text=text, voice="v1",
                     confidence=confidence)


class TestWhatCountsAsDoubt:
    def test_below_the_threshold_is_doubtful(self) -> None:
        assert is_unsure(said(0, "qui nous réplique", 0.61))

    def test_above_it_is_not(self) -> None:
        assert not is_unsure(said(0, "la recette est prête", 0.95))

    def test_a_turn_nobody_judged_is_not_doubtful(self) -> None:
        # No figure is not a low figure. Marking these would teach people to
        # ignore the mark, and whisper.cpp returns none at all.
        assert not is_unsure(said(0, "d'accord", None))

    def test_the_threshold_sits_in_the_gap_that_was_measured(self) -> None:
        # Clean speech and +10 dB came back at 0.91 and above, +5 dB and worse
        # at 0.81 and below. Nothing was observed between the two.
        assert 0.81 < UNSURE_BELOW < 0.91


class TestCountingThem:
    def test_it_counts_the_doubtful_out_of_the_judged(self) -> None:
        account = count([
            said(0, "un", 0.95), said(3, "deux", 0.61),
            said(6, "trois", None), said(9, "quatre", 0.70),
        ])
        assert account == Doubts(turns=4, unsure=2, judged=3)
        assert account.share == 2 / 3

    def test_a_meeting_nobody_judged_has_no_share_rather_than_a_crash(self) -> None:
        account = count([said(0, "un", None)])
        assert (account.judged, account.share) == (0, 0.0)

    def test_the_doubtful_turns_come_back_earliest_first(self) -> None:
        turns = worth_listening_again([
            said(9, "tard", 0.5), said(1, "tôt", 0.5), said(5, "entre", 0.95),
        ])
        assert [u.text for u in turns] == ["tôt", "tard"]


class TestWhenItIsWorthSaying:
    def test_one_turn_in_a_hundred_is_noise(self) -> None:
        account = count([said(i, "oui", 0.95) for i in range(99)]
                        + [said(300, "peut-être", 0.4)])
        assert not account.worth_saying
        assert said_in_french(account) == ""

    def test_a_tenth_of_them_is_worth_a_line(self) -> None:
        account = count([said(i, "oui", 0.95) for i in range(9)]
                        + [said(30, "peut-être", 0.4)])
        assert account.worth_saying
        assert MARK in said_in_french(account)

    def test_a_meeting_it_is_sure_of_says_nothing(self) -> None:
        assert said_in_french(count([said(0, "oui", 0.95)])) == ""

    def test_the_sentence_agrees_with_itself(self) -> None:
        un = said_in_french(count([said(0, "peut-être", 0.4)] +
                                   [said(i + 1, "oui", 0.95) for i in range(4)]))
        plusieurs = said_in_french(count([said(0, "a", 0.4), said(2, "b", 0.4)] +
                                          [said(i + 4, "oui", 0.95) for i in range(8)]))
        assert "1 passage sur 5 mérite une réécoute" in un
        assert "2 passages sur 10 méritent une réécoute" in plusieurs
