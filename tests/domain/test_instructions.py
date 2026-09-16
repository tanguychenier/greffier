"""What, during the meeting, calls for an action."""

from greffier.domain.instructions import (
    Kind,
    Origin,
    WatchRules,
    decisions_in,
    instruction_after,
    links_in,
)
from greffier.domain.models import Span, Utterance
from greffier.domain.profiles.french import FRENCH


def utterance(start, text):
    return Utterance(span=Span(start, start + 5), text=text)


class TestPastedLinks:
    def test_a_pasted_address_is_picked_up(self):
        assert links_in("voir https://miro.com/board/abc123") == ["https://miro.com/board/abc123"]

    def test_the_final_punctuation_is_not_part_of_the_link(self):
        assert links_in("c'est ici : https://exemple.fr/page.") == ["https://exemple.fr/page"]

    def test_several_addresses_without_duplicates_and_in_order(self):
        text = "https://a.fr puis https://b.fr et encore https://a.fr"
        assert links_in(text) == ["https://a.fr", "https://b.fr"]

    def test_a_link_said_out_loud_is_not_claimed_as_read(self):
        """« miro point com slash board » does not give a valid address:
        better to propose nothing than to propose anything."""
        assert links_in("va voir sur miro point com slash board slash b n 7 x") == []

    def test_a_text_without_a_link_produces_nothing(self):
        assert links_in("on se revoit jeudi pour la recette") == []


class TestTheKeyword:
    def test_what_follows_the_word_is_the_instruction(self):
        assert instruction_after("Greffier, ouvre le ticket 1234", "greffier") == \
            "ouvre le ticket 1234"

    def test_the_word_is_recognised_whatever_the_case(self):
        assert instruction_after("greffier note cette décision", "greffier") == \
            "note cette décision"

    def test_the_instruction_stops_at_the_end_of_the_sentence(self):
        """Beyond that, the person has moved on to something else."""
        text = "Greffier, note ça. Sinon, on parle du budget maintenant."
        assert instruction_after(text, "greffier") == "note ça"

    def test_without_the_word_there_is_no_instruction(self):
        assert instruction_after("on ouvre le ticket 1234", "greffier") is None

    def test_the_word_alone_with_nothing_after_produces_nothing(self):
        assert instruction_after("Greffier.", "greffier") is None


class TestDecisions:
    def test_the_wordings_of_a_decision_are_spotted(self):
        for text in ["on décide de décaler", "il faut qu'on prévienne",
                      "je m'en charge", "à faire : relancer", "d'ici jeudi"]:
            assert decisions_in(text, FRENCH), text

    def test_an_ordinary_sentence_is_not_a_decision(self):
        assert not decisions_in("le déploiement s'est bien passé hier", FRENCH)


class TestTheWatchRules:
    def test_an_instruction_is_picked_up_once(self):
        """The running transcription goes over the same passages again."""
        watch_rules = WatchRules(profile=FRENCH)
        utterances = [utterance(10, "Greffier, ouvre le ticket 1234")]
        assert len(watch_rules.listen(utterances)) == 1
        assert watch_rules.listen(utterances) == []

    def test_a_link_pasted_twice_is_offered_once(self):
        watch_rules = WatchRules(profile=FRENCH)
        assert len(watch_rules.paste("https://miro.com/x", 5)) == 1
        assert watch_rules.paste("https://miro.com/x", 30) == []

    def test_where_it_came_from_is_kept(self):
        """The clipboard is exact, speech is transcribed: the reliability is
        not the same and the reader has to be able to judge it."""
        watch_rules = WatchRules(profile=FRENCH)
        watch_rules.paste("https://a.fr", 1)
        watch_rules.listen([utterance(2, "Greffier, note le sujet")])
        origins = {p.origin for p in watch_rules.propositions}
        assert origins == {Origin.CLIPBOARD, Origin.SPEECH}

    def test_an_instruction_is_not_reclassed_as_a_decision(self):
        watch_rules = WatchRules(profile=FRENCH)
        watch_rules.listen([utterance(3, "Greffier, note qu'il faut qu'on relance")])
        assert [p.kind for p in watch_rules.propositions] == [Kind.INSTRUCTION]

    def test_the_context_of_the_instruction_is_kept(self):
        watch_rules = WatchRules(profile=FRENCH)
        watch_rules.listen([utterance(3, "Bon, Greffier, ouvre le tableau")])
        assert "Bon," in watch_rules.propositions[0].context

    def test_another_keyword_can_be_chosen(self):
        watch_rules = WatchRules(keyword="assistant", profile=FRENCH)
        watch_rules.listen([utterance(1, "Assistant, note ce point")])
        assert watch_rules.propositions[0].text == "note ce point"

    def test_sorting_by_kind(self):
        watch_rules = WatchRules(profile=FRENCH)
        watch_rules.paste("https://a.fr https://b.fr", 1)
        watch_rules.listen([utterance(2, "on décide de reporter la mise en production")])
        assert len(watch_rules.by_gender(Kind.LINK)) == 2
        assert len(watch_rules.by_gender(Kind.DECISION)) == 1
