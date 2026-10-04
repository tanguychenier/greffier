"""A meeting prepared before it is held.

The conversation already answered outside a meeting and led nowhere: it spoke of
a meeting that already existed, never of the one about to be held. What was
gathered stayed in a corner while the meeting started from nothing.
"""

from __future__ import annotations

from greffier.domain.preparation import PREPARATION_MAXIMUM, Preparation, question_prompt


def _one(**champs) -> Preparation:
    return Preparation(identifier="2026-09-12_10h00_preparation", **champs)


class TestWhatItGathers:
    def test_a_question_and_its_answer_are_kept_in_order(self):
        p = _one().asked("rappelle-moi la dernière", "Décalée à jeudi.").asked("et Jira ?")
        assert [e.asked for e in p.exchanges] == ["rappelle-moi la dernière", "et Jira ?"]
        assert p.exchanges[0].answered == "Décalée à jeudi."

    def test_an_empty_question_is_not_an_exchange(self):
        assert _one().asked("   ").exchanges == ()

    def test_a_question_without_an_answer_yet_is_kept_with_none(self):
        assert _one().asked("et Jira ?").exchanges[0].answered == ""

    def test_a_point_said_twice_is_raised_once(self):
        p = _one().raising("valider les anomalies").raising("valider  les anomalies")
        assert p.to_raise == ("valider les anomalies",)

    def test_the_people_expected_are_kept_once_each(self):
        p = _one().expecting("Sophie").expecting("Sophie").expecting("Jacques")
        assert p.expected == ("Sophie", "Jacques")

    def test_a_name_said_with_extra_blanks_is_kept_with_one(self):
        assert _one().expecting("Sophie   Durand").expected == ("Sophie Durand",)

    def test_a_document_alone_is_something_gathered(self):
        assert _one(documents=("cahier.pdf",)).available

    def test_gathering_nothing_leaves_it_empty(self):
        assert _one().empty
        assert not _one().available


class TestBeingTakenByAMeeting:
    def test_what_was_gathered_waits_for_a_meeting(self):
        assert _one().raising("un point").available

    def test_a_meeting_takes_it_once(self):
        """Two meetings opening on the same material would each believe it theirs."""
        p = _one().raising("un point").taken("2026-09-12_reunion")
        assert not p.available
        assert p.taken_by == "2026-09-12_reunion"


class TestWhatTheMeetingOpensOn:
    def test_the_points_to_raise_come_first(self):
        """What somebody thought to ask beforehand is what they want out of it."""
        header = _one(subject="recette").raising("valider les anomalies").header()
        assert header.index("Points à soulever") < header.index("recette") + 200
        assert "valider les anomalies" in header

    def test_the_people_expected_come_with_their_warning(self):
        header = _one().expecting("Jacques").header()
        assert "Jacques" in header
        assert "montre la présence" in header, (
            "annoncer qui est attendu ne doit pas devenir une autorisation "
            "d'attribuer des propos"
        )

    def test_an_empty_preparation_opens_on_nothing(self):
        assert _one().header() == ""

    def test_the_documents_are_listed_on_one_line(self):
        p = _one(documents=("cahier.pdf", "planning.xlsx"))
        assert p.header() == (
            "[Préparation de cette réunion]\n"
            "Documents rassemblés avant la séance : cahier.pdf, planning.xlsx\n"
            "\n"
        )

    def test_it_is_cut_at_an_exchange_and_never_inside_one(self):
        """Half an answer read as a whole one is worse than no answer at all."""
        long_one = _one()
        for number in range(40):
            long_one = long_one.asked(f"question {number}", "r" * 300)
        header = long_one.header()
        assert len(header) <= PREPARATION_MAXIMUM + 400
        assert "répondu : " + "r" * 300 in header, "une réponse entière, ou aucune"

    def test_the_most_recent_exchanges_are_the_ones_kept(self):
        long_one = _one()
        for number in range(40):
            long_one = long_one.asked(f"question {number}", "r" * 300)
        header = long_one.header()
        assert "question 39" in header and "question 0" not in header

    def test_the_room_left_to_the_exchanges_is_counted_to_the_character(self):
        """One character short, and the exchange is left out rather than cut."""
        frame = "[Préparation de cette réunion]"
        intro = ("Ce qui a été demandé avant la réunion, et ce qui a été répondu. "
                 "N'y reviens que si la séance y touche :")
        one, other = "- demandé : q", "- demandé : r"
        room = len(frame) + len(one) + 1
        both = room + len(other) + 1
        p = _one().asked("q").asked("r")
        assert _one().asked("q").header(place=room) == f"{frame}\n\n{intro}\n{one}\n\n"
        assert _one().asked("q").header(place=room - 1) == f"{frame}\n\n"
        assert p.header(place=both) == f"{frame}\n\n{intro}\n{one}\n{other}\n\n"
        assert p.header(place=both - 1) == f"{frame}\n\n{intro}\n{other}\n\n"

    def test_the_header_in_full(self):
        """What the writer reads, line by line; the frame is a promise as much as the content."""
        p = (
            _one(subject="recette", documents=("cahier-de-recette.pdf", "planning.xlsx"))
            .raising("valider les anomalies").raising("fixer la date")
            .expecting("Sophie").expecting("Jacques")
            .asked("rappelle-moi la dernière", "Décalée à jeudi.").asked("et Jira ?")
        )
        assert p.header() == (
            "[Préparation de cette réunion]\n"
            "Sujet annoncé : recette\n"
            "Points à soulever, dans l'ordre où ils ont été notés :\n"
            "- valider les anomalies\n"
            "- fixer la date\n"
            "Personnes attendues : Sophie, Jacques. N'attribue un propos qu'à quelqu'un "
            "dont la transcription montre la présence.\n"
            "Documents rassemblés avant la séance : cahier-de-recette.pdf, planning.xlsx\n"
            "\n"
            "Ce qui a été demandé avant la réunion, et ce qui a été répondu. "
            "N'y reviens que si la séance y touche :\n"
            "- demandé : rappelle-moi la dernière\n"
            "  répondu : Décalée à jeudi.\n"
            "- demandé : et Jira ?\n"
            "\n"
        )


class TestWhatTheModelIsToldWhenPreparing:
    """The question first, then the rule, then the setting and the material."""

    def test_the_prompt_in_full(self):
        p = _one().raising("un point")
        assert question_prompt(p, "[Contexte] FAST = formulaire", " et alors ? ") == (
            "Question : et alors ?\n\n"
            "Cette réunion n'a pas encore eu lieu : on la prépare. Réponds à la question, "
            "brièvement, pour quelqu'un qui parle et qui écoutera la réponse à voix haute. "
            "N'invente aucun propos tenu en séance, et dis quand tu ne sais pas.\n\n"
            "[Contexte] FAST = formulaire\n"
            + p.header()
        )

    def test_with_nothing_gathered_and_no_setting_the_prompt_ends_on_the_rule(self):
        """Nothing is appended for what is not there, not even a line break."""
        assert question_prompt(_one(), "", "et alors ?") == (
            "Question : et alors ?\n\n"
            "Cette réunion n'a pas encore eu lieu : on la prépare. Réponds à la question, "
            "brièvement, pour quelqu'un qui parle et qui écoutera la réponse à voix haute. "
            "N'invente aucun propos tenu en séance, et dis quand tu ne sais pas.\n\n"
        )
