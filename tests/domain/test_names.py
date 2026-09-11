"""The rules that give a voice a name, with no audio and no model."""

from greffier.domain.models import Span, SpeakerTurn, Utterance
from greffier.domain.names import (
    MentionKind,
    attribute,
    join_namesakes,
    spot_mentions,
)
from greffier.domain.profiles.french import FRENCH


def utterance(start: float, end: float, text: str) -> Utterance:
    return Utterance(span=Span(start, end), text=text)

def _mentions_in(utterances, excluded=None):
    """The French profile, spelled out, as the chain resolves it at runtime.

    These thirty tests have guarded the first-name rules since the first real
    meetings. The profile makes them configurable; not one of their assertions
    changes, and that is what proves the move cost nothing.
    """
    return spot_mentions(utterances, FRENCH, excluded)


def turn(start: float, end: float, voice: str) -> SpeakerTurn:
    return SpeakerTurn(span=Span(start, end), voice=voice)


class TestSpottingAFirstName:
    def test_introducing_oneself(self):
        mentions = _mentions_in([utterance(0, 4, "Bonjour, moi c'est Tanguy, de la DSI.")])
        assert [(m.name, m.type) for m in mentions] == [
            ("Tanguy", MentionKind.AUTO_PRESENTATION)
        ]

    def test_addressing_someone(self):
        mentions = _mentions_in([utterance(0, 3, "Josiane, tu peux nous faire le point ?")])
        assert mentions[0].name == "Josiane"
        assert mentions[0].type is MentionKind.INTERPELLATION

    def test_handing_over_the_floor(self):
        mentions = _mentions_in([utterance(0, 3, "Je passe la parole à Sophie.")])
        assert (mentions[0].name, mentions[0].type) == ("Sophie", MentionKind.INTERPELLATION)

    def test_referring_back(self):
        mentions = _mentions_in([utterance(0, 2, "Merci Marc pour la démonstration.")])
        assert (mentions[0].name, mentions[0].type) == ("Marc", MentionKind.RENVOI)

    def test_everyday_tools_are_not_first_names(self):
        """Without that exclusion, "merci Jira" would create a participant."""
        texts = ["Merci Jira.", "Je suis Teams.", "Merci Outlook."]
        assert _mentions_in([utterance(0, 2, t) for t in texts]) == []

    def test_further_exclusions_from_the_settings(self):
        mentions = _mentions_in(
            [utterance(0, 2, "Merci Oasis pour le retour.")],
            excluded=frozenset({"oasis"}),
        )
        assert mentions == []

    def test_one_position_produces_one_mention(self):
        """"C'est Marc" and "Marc, tu" overlap: the strong pattern wins."""
        mentions = _mentions_in([utterance(0, 3, "Marc, tu peux répondre ?")])
        assert len(mentions) == 1
        assert mentions[0].type is MentionKind.INTERPELLATION


class TestGivingAVoiceAName:
    def test_introducing_oneself_names_the_speaker(self):
        utterances = [utterance(1, 4, "Bonjour, moi c'est Tanguy.")]
        turns = [turn(0, 5, "v1"), turn(5, 10, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        # A single clue of weight 3: enough to be certain.
        assert outcome.certitudes["v1"].name == "Tanguy"

    def test_addressing_someone_names_the_next_speaker(self):
        utterances = [utterance(2, 4, "Josiane, tu peux nous dire où on en est ?")]
        turns = [turn(0, 5, "v1"), turn(6, 20, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert "v1" not in outcome.certitudes
        assert outcome.propositions[0].voice == "v2"
        assert outcome.propositions[0].name == "Josiane"

    def test_referring_back_names_the_previous_speaker(self):
        utterances = [utterance(21, 23, "Merci Marc, c'est clair.")]
        turns = [turn(0, 20, "v2"), turn(20, 30, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.propositions[0].voice == "v2"
        assert outcome.propositions[0].name == "Marc"

    def test_the_clues_add_up_to_certainty(self):
        """Trois renvois faibles valent une auto-présentation."""
        utterances = [
            utterance(21, 22, "Merci Marc."),
            utterance(41, 42, "Comme disait Marc, c'est urgent."),
            utterance(61, 62, "Marc a raison."),
        ]
        turns = [turn(0, 20, "v2"), turn(20, 23, "v1"),
                 turn(23, 40, "v2"), turn(40, 43, "v1"),
                 turn(43, 60, "v2"), turn(60, 63, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certitudes["v2"].name == "Marc"
        assert outcome.certitudes["v2"].score == 3

    def test_a_clue_outside_the_window_does_not_count(self):
        """A "merci Marc" two minutes later names nobody any more."""
        utterances = [utterance(200, 202, "Merci Marc.")]
        turns = [turn(0, 20, "v2"), turn(199, 210, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certitudes == {}
        assert outcome.propositions == []

    def test_one_name_cannot_point_at_two_voices(self):
        """Deux voix revendiquant « Marc » : la mieux étayée le garde."""
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),        # v1, poids 3
            utterance(11, 12, "Merci Marc."),          # renvoie vers v1 aussi
            utterance(31, 32, "Merci Marc."),          # renvoie vers v3
        ]
        turns = [turn(0, 5, "v1"), turn(5, 10, "v2"), turn(10, 15, "v2"),
                 turn(20, 30, "v3"), turn(30, 35, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certitudes["v1"].name == "Marc"
        assert all(a.voice != "v1" for a in outcome.propositions)

    def test_a_credible_rival_prevents_certainty(self):
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),
            utterance(1, 3, "Moi c'est Pascal."),
        ]
        turns = [turn(0, 10, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certitudes == {}
        assert {p.name for p in outcome.propositions} == {"Marc"}


class TestWhatOnlyLooksLikeAName:
    """Cas relevés sur de vraies transcriptions."""

    def test_tu_vois_is_a_verbal_tic(self):
        """"un macro Kanban, tu vois" does not make Kanban a participant."""
        assert _mentions_in([utterance(0, 3, "plus un macro Kanban, tu vois,")]) == []

    def test_vous_savez_is_not_one_either(self):
        assert _mentions_in([utterance(0, 3, "le déploiement Copernic, vous savez bien")]) == []

    def test_but_a_real_address_is_still_caught(self):
        mentions = _mentions_in([utterance(0, 3, "Sophie, tu peux nous dire ?")])
        assert mentions and mentions[0].name == "Sophie"


class TestWordingsHeardInRealMeetings:
    """Sentences taken as they stand from the meeting of 2026-08-20."""

    def test_you_comma_first_name(self):
        m = _mentions_in([utterance(0, 3, "Mais pour ça, toi, Josiane, c'est pas besoin ?")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.INTERPELLATION)]

    def test_a_first_name_leading_into_an_address(self):
        m = _mentions_in([utterance(0, 3, "Josiane, on a lu ensemble et tu nous diras")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.INTERPELLATION)]

    def test_one_word_alone_does_not_make_a_first_name(self):
        """« Ouais. », « Exact. », « Complètement. » remplissent les transcriptions."""
        texts = ["Ouais.", "Exact.", "Complètement.", "Josiane."]
        assert _mentions_in([utterance(i, i + 1, t) for i, t in enumerate(texts)]) == []

    def test_one_word_counts_when_the_name_is_known_elsewhere(self):
        """"Josiane." on its own is a call, once it is known that Josiane exists."""
        m = _mentions_in([
            utterance(0, 3, "Mais pour ça, toi, Josiane, c'est pas besoin ?"),
            utterance(10, 11, "Ouais."),
            utterance(20, 21, "Josiane."),
        ])
        assert [x.name for x in m] == ["Josiane", "Josiane"]

    def test_what_so_and_so_was_presenting(self):
        m = _mentions_in([utterance(0, 3, "pour ce que présentait Josiane.")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.RENVOI)]

    def test_an_opening_of_a_sentence_is_not_a_first_name(self):
        """« Bref, tu vois… », « Après, on verra… » : rien à retenir."""
        texts = ["Bref, tu vois ce que je veux dire.", "Après, on verra bien.",
                  "Donc, vous avez compris.", "Mais, tu sais bien."]
        assert _mentions_in([utterance(0, 2, t) for t in texts]) == []


class TestInterjections:
    """Taken from the meeting of 2026-08-20: "Tiens, tu as vu ?"."""

    def test_tiens_is_not_a_first_name(self):
        assert _mentions_in([utterance(0, 3, "Tiens, tu as vu le ticket ?")]) == []

    def test_adverbs_ending_in_ment_are_dropped(self):
        """No French first name ends in "-ment"; adverbs do."""
        texts = ["Effectivement, tu as raison.", "Normalement, vous livrez jeudi.",
                  "Franchement, on n'y arrivera pas."]
        assert _mentions_in([utterance(i, i + 2, t) for i, t in enumerate(texts)]) == []

    def test_but_clement_is_still_a_first_name(self):
        """The rule must not bite into short first names ending in "-ment"."""
        mentions = _mentions_in([utterance(0, 3, "Clément, tu peux nous dire ?")])
        assert [m.name for m in mentions] == ["Clément"]


class TestBeingAddressedWithNoAnswer:
    """25 August 2026: three calls by name, never an answer.

    The person addressed did not say a word in the whole hour. Each call was
    carried over to the next speaker, and their first name was firmly attributed
    to the voice holding 64% of the speaking time.
    """

    def test_three_calls_do_not_give_certainty(self):
        utterances = [
            utterance(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            utterance(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
            utterance(70, 72, "Vas-y Tanguy, je veux bien que tu partages."),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"),
                 turn(39, 42, "v1"), turn(42, 69, "v2"),
                 turn(69, 72, "v1"), turn(72, 99, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        # Six points gathered, well over the threshold, and still nothing is
        # asserted: all three clues may point at somebody who is not there.
        assert outcome.certitudes == {}

    def test_but_the_name_is_still_offered(self):
        # Proposer garde l'information sans la présenter comme acquise : c'est
        # à l'utilisateur de trancher, en écoutant dix secondes.
        utterances = [
            utterance(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            utterance(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"),
                 turn(39, 42, "v1"), turn(42, 69, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert [p.name for p in outcome.propositions] == ["Tanguy"]

    def test_a_call_confirmed_by_a_reference_back_is_enough(self):
        # "Sandy, tu peux…" then "Merci Sandy": two directions agree, one of
        # them pointing at somebody who did speak.
        utterances = [
            utterance(10, 12, "Sandy, tu peux nous dire où en sont les anomalies ?"),
            utterance(40, 42, "Merci Sandy."),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"), turn(39, 42, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certitudes["v2"].name == "Sandy"

    def test_introducing_oneself_is_always_enough_alone(self):
        # The person names themselves: there is nothing speculative in that.
        utterances = [utterance(0, 4, "Bonjour, moi c'est Jacques, je commence.")]
        turns = [turn(0, 20, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certitudes["v1"].name == "Jacques"


class TestJoiningNamesakesAfterTheMeeting:
    """Two voices given the same name are the same person.

    Measured on a real meeting of one hour forty-two: the chain concluded "Lise"
    on nine distinct voices, eight of them of a single turn. The minutes therefore
    announced eight participants too many. The same rule had existed for the live
    thread since that morning; the after-meeting chain lacked it.
    """

    def test_nine_voices_of_one_name_make_one(self) -> None:
        names = {f"v{i}": "Lise" for i in range(9)}
        poids = {f"v{i}": float(i) for i in range(9)}
        membership = join_namesakes(names, poids)
        assert len(set(membership.values())) == 1

    def test_the_best_fed_voice_wins(self) -> None:
        """It is the one whose extract is the most representative."""
        names = {"maigre": "Lise", "fournie": "Lise"}
        membership = join_namesakes(names, {"maigre": 3.0, "fournie": 240.0})
        assert set(membership.values()) == {"fournie"}

    def test_two_different_names_do_not_touch(self) -> None:
        names = {"v1": "Lise", "v2": "Pascal"}
        membership = join_namesakes(names, {"v1": 10.0, "v2": 20.0})
        assert membership == {"v1": "v1", "v2": "v2"}

    def test_case_and_accents_do_not_make_two_people(self) -> None:
        names = {"v1": "Hélène", "v2": "helene", "v3": "HÉLÈNE"}
        membership = join_namesakes(names, {"v1": 5.0, "v2": 9.0, "v3": 1.0})
        assert set(membership.values()) == {"v2"}

    def test_a_voice_with_no_known_weight_breaks_nothing(self) -> None:
        names = {"v1": "Lise", "v2": "Lise"}
        membership = join_namesakes(names, {})
        assert len(set(membership.values())) == 1

    def test_an_empty_name_is_ignored(self) -> None:
        names = {"v1": "  ", "v2": "  ", "v3": "Pascal"}
        membership = join_namesakes(names, {"v1": 1.0, "v2": 2.0, "v3": 3.0})
        assert membership["v1"] == "v1"
        assert membership["v2"] == "v2"

    def test_every_voice_appears_in_the_membership(self) -> None:
        """The caller applies the result without having to fill in the gaps."""
        names = {"v1": "Lise", "v2": "Lise", "v3": "Pascal"}
        membership = join_namesakes(names, {"v1": 1.0, "v2": 2.0, "v3": 3.0})
        assert set(membership) == {"v1", "v2", "v3"}
