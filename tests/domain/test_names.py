"""The rules that give a voice a name, with no audio and no model."""

import re
import unicodedata

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.language import Detection, LanguageProfile
from greffier.domain.models import Span, SpeakerTurn, Utterance
from greffier.domain.names import (
    FOLLOWING_WINDOW,
    PREVIOUS_WINDOW,
    TOLERATED_GAP,
    WEIGHT,
    Mention,
    MentionKind,
    attribute,
    join_namesakes,
    spot_mentions,
    target,
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


def mention(start: float, end: float, name: str, kind: MentionKind) -> Mention:
    """A spoken name placed by hand, to ask where it points without a transcript."""
    return Mention(name=name, span=Span(start, end), type=kind, excerpt=f"… {name} …")


def folded(name: str) -> str:
    """What is left of a name once case, accents and blanks are taken away."""
    stripped = unicodedata.normalize("NFD", name.strip().casefold())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


# The whole meeting fits in two minutes: a longer clock would only spread the
# examples thinner over the windows the rules are measured in.
_INSTANTS = st.floats(min_value=0.0, max_value=120.0, allow_nan=False, allow_infinity=False)
_VOICES = ["v1", "v2", "v3"]
# Two spellings of two names, so that the "one name, one voice" rule has
# namesakes to settle across case and accents.
_NAMES = ["Marc", "marc", "Hélène", "Helene", "Zoé"]


def some_spans() -> st.SearchStrategy[Span]:
    return st.tuples(_INSTANTS, _INSTANTS).map(lambda pair: Span(min(pair), max(pair)))


def some_turns(min_size: int = 0) -> st.SearchStrategy[list[SpeakerTurn]]:
    one = st.builds(SpeakerTurn, span=some_spans(), voice=st.sampled_from(_VOICES))
    return st.lists(one, min_size=min_size, max_size=6)


def some_mentions() -> st.SearchStrategy[list[Mention]]:
    """Mentions as spot_mentions hands them over: sorted by the instant they were said."""
    one = st.builds(
        Mention,
        name=st.sampled_from(_NAMES),
        span=some_spans(),
        type=st.sampled_from(list(MentionKind)),
        excerpt=st.just("…"),
    )
    return st.lists(one, max_size=8).map(lambda found: sorted(found, key=lambda m: m.at_instant))


def first_names() -> st.SearchStrategy[str]:
    """Capitalised words the French profile takes for first names on their own."""
    return st.builds(
        str.__add__,
        st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=11),
    ).filter(
        lambda name: name.lower() not in FRENCH.detection.excluded
        and not (len(name) >= 8 and name.endswith("ment"))
    )


@st.composite
def a_sentence_nobody_speaks_over(draw):
    """A span with turns before it and after it, never across it."""
    start = draw(st.floats(min_value=20.0, max_value=100.0))
    length = draw(st.floats(min_value=0.1, max_value=5.0))
    span = Span(start, start + length)
    before = st.tuples(st.floats(0.0, span.start), st.floats(0.0, span.start))
    after = st.tuples(st.floats(span.end, 200.0), st.floats(span.end, 200.0))
    around = st.one_of(before, after).map(lambda pair: Span(min(pair), max(pair)))
    turns = draw(st.lists(
        st.builds(SpeakerTurn, span=around, voice=st.sampled_from(_VOICES)),
        min_size=1, max_size=5,
    ))
    return span, turns


class TestSpottingAFirstName:
    def test_introducing_oneself(self):
        mentions = _mentions_in([utterance(0, 4, "Bonjour, moi c'est Tanguy, de la DSI.")])
        assert [(m.name, m.type) for m in mentions] == [
            ("Tanguy", MentionKind.AUTO_PRESENTATION)
        ]

    def test_addressing_someone(self):
        mentions = _mentions_in([utterance(0, 3, "Josiane, tu peux nous faire le point ?")])
        assert mentions[0].name == "Josiane"
        assert mentions[0].type is MentionKind.ADDRESSING

    def test_handing_over_the_floor(self):
        mentions = _mentions_in([utterance(0, 3, "Je passe la parole à Sophie.")])
        assert (mentions[0].name, mentions[0].type) == ("Sophie", MentionKind.ADDRESSING)

    def test_referring_back(self):
        mentions = _mentions_in([utterance(0, 2, "Merci Marc pour la démonstration.")])
        assert (mentions[0].name, mentions[0].type) == ("Marc", MentionKind.REFERRAL)

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
        assert mentions[0].type is MentionKind.ADDRESSING

    def test_the_stronger_reading_wins_whichever_pattern_comes_first(self):
        """"Merci Marc, tu peux continuer ?": thanked and called at one position.

        The call weighs more than the thanks, and it is read first; the thanks
        must not overwrite it just because its pattern comes later in the list.
        """
        mentions = _mentions_in([utterance(0, 3, "Merci Marc, tu peux continuer ?")])
        assert [(m.name, m.type) for m in mentions] == [("Marc", MentionKind.ADDRESSING)]

    def test_the_same_name_at_two_places_of_one_sentence_is_two_clues(self):
        """"Marc, tu commences" calls the next speaker, "merci Marc" thanks the previous."""
        mentions = _mentions_in([utterance(0, 4, "Marc, tu commences, et merci Marc pour hier.")])
        assert [m.type for m in mentions] == [MentionKind.ADDRESSING, MentionKind.REFERRAL]

    def test_three_letters_make_a_first_name_two_do_not(self):
        """Léo, Max and Eva are first names; at two letters "Ah" and "Eh" would be too."""
        assert [m.name for m in _mentions_in([utterance(0, 2, "Merci Léo.")])] == ["Léo"]
        assert _mentions_in([utterance(0, 2, "Merci Al.")]) == []

    def test_an_excluded_word_does_not_hide_the_name_that_follows_it(self):
        """"Merci Teams, et merci Marc": the tool is skipped, the person is kept."""
        mentions = _mentions_in([utterance(0, 3, "Merci Teams, et merci Marc pour la démo.")])
        assert [(m.name, m.type) for m in mentions] == [("Marc", MentionKind.REFERRAL)]

    def test_the_transcribers_curly_apostrophe_excludes_the_same_words(self):
        """Whisper writes « aujourd’hui » with a typographic apostrophe.

        The exclusion list is spelled with the straight one; it has to bite on
        both, or every meeting opens with a participant called Aujourd’hui.
        """
        mentions = _mentions_in([utterance(0, 3, "Aujourd’hui, tu peux nous dire où on en est ?")])
        assert mentions == []

    def test_the_excerpt_is_the_sentence_the_name_was_heard_in(self):
        """It is what a person reads to check an attribution, without the blanks
        the transcriber leaves around a segment."""
        mentions = _mentions_in([utterance(0, 2, "  Merci Marc pour la démonstration. ")])
        assert mentions[0].excerpt == "Merci Marc pour la démonstration."


class TestWordsTheMeetingAlsoSaysInLowerCase:
    """A word the meeting spells in lower case somewhere is a word, not a person."""

    def test_a_word_heard_in_lower_case_is_not_a_first_name(self):
        """"Merci Tempête" alone would create a participant; "la tempête" says it is weather."""
        mentions = _mentions_in([
            utterance(0, 3, "On a vu la tempête hier soir."),
            utterance(10, 12, "Merci Tempête."),
        ])
        assert mentions == []

    def test_a_capital_inside_the_word_does_not_make_it_a_person(self):
        """"iPhone" starts in lower case and still carries a capital: a thing, not a name,
        even when the transcriber capitalises it at the start of a sentence."""
        mentions = _mentions_in([
            utterance(0, 3, "On a testé la version sur iPhone."),
            utterance(10, 12, "Iphone, on le garde dans le périmètre ?"),
        ])
        assert mentions == []

    @given(first_names())
    def test_one_lower_case_spelling_anywhere_disqualifies_the_word(self, name):
        thanks = utterance(0, 2, f"Merci {name}.")
        assert [m.name for m in _mentions_in([thanks])] == [name]
        aside = utterance(10, 12, f"on avait parlé de {name.lower()} la dernière fois")
        assert _mentions_in([thanks, aside]) == []


class TestAWidePatternConfirmedByAKnownName:
    """A wide pattern is kept only for a name a firm pattern already found.

    The French wide pattern is a name alone in its sentence, so it never
    matches twice in one. A profile whose wide pattern can is where the order
    of the matches starts to matter.
    """

    def test_an_unknown_word_does_not_hide_a_known_name_later_in_the_sentence(self):
        firm = (MentionKind.REFERRAL, re.compile(r"(?i:\bthanks)\s+(?P<nom>[A-Z]\w+)"), False)
        wide = (MentionKind.ADDRESSING, re.compile(r"(?i:\bhello)\s+(?P<nom>[A-Z]\w+)"), True)
        profile = LanguageProfile(
            code="xx", name="Synthetic", detection=Detection(active=True, motifs=(firm, wide)),
        )
        utterances = [utterance(0, 2, "Thanks Marc."), utterance(5, 8, "Hello Paul, hello Marc.")]
        mentions = spot_mentions(utterances, profile)
        assert [(m.name, m.type) for m in mentions] == [
            ("Marc", MentionKind.REFERRAL), ("Marc", MentionKind.ADDRESSING),
        ]


class TestWhichVoiceSpeaksTheSentence:
    """Whisper's and the diariser's timings never agree to the fraction of a second."""

    def introduction(self, start: float, end: float) -> Mention:
        return mention(start, end, "Marc", MentionKind.AUTO_PRESENTATION)

    def test_the_voice_holding_most_of_the_sentence_is_the_speaker(self):
        turns = [turn(0, 5, "v2"), turn(5, 10, "v1")]
        assert target(self.introduction(4.5, 6.5), turns) == "v1"

    def test_a_voice_cut_into_several_turns_adds_them_up(self):
        """The diariser splits a sentence around a short interjection: 0.5 s and
        0.8 s of one voice outweigh the 1.2 s of the other."""
        turns = [turn(0, 1, "v1"), turn(1, 2.2, "v2"), turn(2.2, 3, "v1")]
        assert target(self.introduction(0.5, 3.0), turns) == "v1"

    @given(some_spans(), some_turns())
    def test_the_speaker_is_the_voice_with_the_most_time_under_the_sentence(self, span, turns):
        held: dict[str, float] = {}
        for one in turns:
            shared = span.overlap(one.span)
            if shared > 0:
                held[one.voice] = held.get(one.voice, 0.0) + shared
        voice = target(Mention("Marc", span, MentionKind.AUTO_PRESENTATION, "…"), turns)
        if held:
            assert voice is not None
            assert held[voice] == max(held.values())

    def test_a_sentence_falling_just_after_a_turn_belongs_to_that_voice(self):
        turns = [turn(0, 10, "v1"), turn(12, 20, "v2")]
        assert target(self.introduction(10.2, 11), turns) == "v1"

    def test_a_sentence_falling_just_before_a_turn_belongs_to_that_voice(self):
        turns = [turn(0, 10, "v1"), turn(12, 20, "v2")]
        assert target(self.introduction(11, 11.8), turns) == "v2"

    def test_three_seconds_of_silence_still_join_the_sentence_to_the_voice(self):
        """Exactly the tolerated gap is tolerated; a tenth of a second more is not."""
        sentence = self.introduction(5, 10)
        assert target(sentence, [turn(10 + TOLERATED_GAP, 20, "v1")]) == "v1"
        assert target(sentence, [turn(10 + TOLERATED_GAP + 0.1, 20, "v1")]) is None

    def test_a_sentence_with_no_turn_at_all_belongs_to_nobody(self):
        assert target(self.introduction(5, 10), []) is None

    @given(a_sentence_nobody_speaks_over())
    def test_a_sentence_nobody_covers_goes_to_the_nearest_voice_within_the_gap(self, case):
        span, turns = case
        def gap(one: SpeakerTurn) -> float:
            return min(abs(one.span.start - span.end), abs(span.start - one.span.end))
        nearest = min(gap(one) for one in turns)
        voice = target(Mention("Marc", span, MentionKind.AUTO_PRESENTATION, "…"), turns)
        if nearest > TOLERATED_GAP:
            assert voice is None
        else:
            assert min(gap(one) for one in turns if one.voice == voice) == nearest

    def test_an_introduction_in_a_gap_between_turns_still_names_its_speaker(self):
        utterances = [utterance(10.3, 11.8, "Moi c'est Marc.")]
        turns = [turn(0, 10, "v1"), turn(12, 20, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certainties["v2"].name == "Marc"


class TestWhoAnswersACall:
    def call(self, start: float, end: float) -> Mention:
        return mention(start, end, "Josiane", MentionKind.ADDRESSING)

    def test_the_answer_comes_from_the_voice_that_speaks_next_not_the_one_before(self):
        turns = [turn(0, 5, "v2"), turn(5, 10, "v1"), turn(11, 20, "v3")]
        assert target(self.call(6, 8), turns) == "v3"

    def test_the_callers_own_next_turn_is_not_the_answer(self):
        """Diarisers cut one speaker at every pause; the answer comes from somebody else."""
        turns = [turn(0, 5, "v1"), turn(5, 10, "v1"), turn(10, 20, "v2")]
        assert target(self.call(2, 4), turns) == "v2"

    def test_a_voice_starting_with_the_call_is_speaking_over_it_not_answering(self):
        turns = [turn(0, 10, "v2"), turn(10, 11, "v1"), turn(11, 30, "v3"), turn(30, 40, "v4")]
        assert target(self.call(10, 14), turns) == "v4"

    def test_an_answer_at_the_edge_of_the_window_counts_a_second_later_does_not(self):
        caller = turn(0, 12, "v1")
        at_the_edge = turn(10 + FOLLOWING_WINDOW, 60, "v2")
        assert target(self.call(10, 12), [caller, at_the_edge]) == "v2"
        a_second_late = turn(10 + FOLLOWING_WINDOW + 1, 60, "v2")
        assert target(self.call(10, 12), [caller, a_second_late]) is None


class TestWhoAThankYouPointsAt:
    def thanks(self, start: float, end: float) -> Mention:
        return mention(start, end, "Marc", MentionKind.REFERRAL)

    def test_it_points_at_who_spoke_before_not_at_who_speaks_after(self):
        turns = [turn(0, 20, "v2"), turn(20, 30, "v1"), turn(30, 40, "v3")]
        assert target(self.thanks(21, 23), turns) == "v2"

    def test_the_thankers_own_earlier_turn_is_not_who_they_thank(self):
        turns = [turn(0, 5, "v2"), turn(5, 10, "v1"), turn(10, 15, "v1")]
        assert target(self.thanks(11, 13), turns) == "v2"

    def test_a_turn_ending_as_the_thanks_begin_is_the_one_thanked(self):
        """The diariser cuts at 21 s and the transcriber starts the sentence at 21 s."""
        turns = [turn(0, 21, "v2"), turn(21, 30, "v1")]
        assert target(self.thanks(21, 23), turns) == "v2"

    def test_a_minute_back_still_counts_a_second_more_does_not(self):
        turns = [turn(0, 20, "v2"), turn(20, 100, "v1")]
        assert target(self.thanks(20 + PREVIOUS_WINDOW, 82), turns) == "v2"
        assert target(self.thanks(20 + PREVIOUS_WINDOW + 1, 83), turns) is None

    def test_thanks_before_anyone_else_has_spoken_point_at_nobody(self):
        assert target(self.thanks(1, 3), [turn(0, 10, "v1")]) is None


class TestGivingAVoiceAName:
    def test_introducing_oneself_names_the_speaker(self):
        utterances = [utterance(1, 4, "Bonjour, moi c'est Tanguy.")]
        turns = [turn(0, 5, "v1"), turn(5, 10, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        # A single clue of weight 3: enough to be certain.
        assert outcome.certainties["v1"].name == "Tanguy"

    def test_addressing_someone_names_the_next_speaker(self):
        utterances = [utterance(2, 4, "Josiane, tu peux nous dire où on en est ?")]
        turns = [turn(0, 5, "v1"), turn(6, 20, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert "v1" not in outcome.certainties
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
        assert outcome.certainties["v2"].name == "Marc"
        assert outcome.certainties["v2"].score == 3

    def test_a_clue_outside_the_window_does_not_count(self):
        """A "merci Marc" two minutes later names nobody any more."""
        utterances = [utterance(200, 202, "Merci Marc.")]
        turns = [turn(0, 20, "v2"), turn(199, 210, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certainties == {}
        assert outcome.propositions == []

    def test_a_clue_pointing_at_nobody_does_not_silence_the_ones_after_it(self):
        """"Merci Marc" before anyone else spoke points at nobody; the introduction
        that follows still counts."""
        utterances = [utterance(1, 2, "Merci Marc."), utterance(5, 7, "Moi c'est Sophie.")]
        outcome = attribute(_mentions_in(utterances), [turn(0, 10, "v1")])
        assert outcome.certainties["v1"].name == "Sophie"

    def test_one_name_cannot_point_at_two_voices(self):
        """Two voices claiming « Marc »: the better supported keeps it."""
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),        # v1, weight 3
            utterance(11, 12, "Merci Marc."),          # points back to v1 as well
            utterance(31, 32, "Merci Marc."),          # points back to v3
        ]
        turns = [turn(0, 5, "v1"), turn(5, 10, "v2"), turn(10, 15, "v2"),
                 turn(20, 30, "v3"), turn(30, 35, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certainties["v1"].name == "Marc"
        assert all(a.voice != "v1" for a in outcome.propositions)

    def test_of_two_certain_voices_the_better_supported_keeps_the_name(self):
        """The diariser split one Marc in two, or two Marcs sat in the room: either
        way one voice is named and the other is offered for the person to settle."""
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),        # v1, weight 3
            utterance(11, 13, "Moi c'est Marc."),      # v3, weight 3
            utterance(21, 22, "Merci Marc."),          # v2 speaking, points back to v3
        ]
        turns = [turn(0, 10, "v1"), turn(10, 20, "v3"), turn(20, 30, "v2")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert [(v, a.name) for v, a in outcome.certainties.items()] == [("v3", "Marc")]
        assert [(p.voice, p.name) for p in outcome.propositions] == [("v1", "Marc")]

    def test_a_credible_rival_prevents_certainty(self):
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),
            utterance(1, 3, "Moi c'est Pascal."),
        ]
        turns = [turn(0, 10, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certainties == {}
        assert {p.name for p in outcome.propositions} == {"Marc"}

    def test_the_best_supported_name_wins_whatever_the_alphabet_says(self):
        """Zoé introduced herself; one "merci Albert" also landed on her voice."""
        utterances = [utterance(1, 3, "Moi c'est Zoé."), utterance(21, 22, "Merci Albert.")]
        turns = [turn(0, 10, "v1"), turn(10, 25, "v2")]
        found = attribute(_mentions_in(utterances), turns).certainties["v1"]
        assert (found.name, found.score) == ("Zoé", 3)
        assert (found.concurrent, found.score_concurrent) == ("Albert", 1)

    def test_a_name_without_a_rival_records_none(self):
        utterances = [utterance(1, 4, "Bonjour, moi c'est Tanguy.")]
        found = attribute(_mentions_in(utterances), [turn(0, 5, "v1")]).certainties["v1"]
        assert found.concurrent is None
        assert found.score_concurrent == 0

    def test_a_tie_between_two_names_is_settled_the_same_way_whoever_spoke_first(self):
        """The minutes must not change with the order the clues were heard in."""
        turns = [turn(0, 10, "v1")]
        marc_first = attribute(_mentions_in([
            utterance(1, 3, "Moi c'est Marc."), utterance(4, 6, "Moi c'est Pascal."),
        ]), turns)
        pascal_first = attribute(_mentions_in([
            utterance(1, 3, "Moi c'est Pascal."), utterance(4, 6, "Moi c'est Marc."),
        ]), turns)
        assert marc_first.certainties == pascal_first.certainties == {}
        assert marc_first.propositions[0].name == pascal_first.propositions[0].name

    def test_a_doubtful_loud_voice_does_not_hide_a_certain_quiet_one(self):
        """Six points of calls to an absent Tanguy outrank Jacques's one introduction;
        the doubt on the first must not swallow the certainty on the second."""
        utterances = [
            utterance(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            utterance(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
            utterance(70, 72, "Vas-y Tanguy, je veux bien que tu partages."),
            utterance(100, 103, "Bonjour, moi c'est Jacques."),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"),
                 turn(39, 42, "v1"), turn(42, 69, "v2"),
                 turn(69, 72, "v1"), turn(72, 99, "v2"), turn(99, 110, "v3")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certainties["v3"].name == "Jacques"
        assert [p.name for p in outcome.propositions] == ["Tanguy"]

    def test_propositions_are_offered_strongest_first(self):
        utterances = [
            utterance(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            utterance(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
            utterance(100, 101, "Merci Marc."),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"), turn(39, 42, "v1"),
                 turn(42, 69, "v2"), turn(69, 99, "v3"), turn(99, 102, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert [(p.voice, p.name, p.score) for p in outcome.propositions] == [
            ("v2", "Tanguy", 4), ("v3", "Marc", 1),
        ]

    @given(some_mentions(), some_turns())
    def test_what_the_outcome_promises_whatever_was_said(self, mentions, turns):
        outcome = attribute(mentions, turns)
        certainties = outcome.certainties
        assert all(voice == found.voice and found.certain
                   for voice, found in certainties.items())
        # One name, one voice: no two certainties share a name, accents and case aside.
        assert len({found.indices[0].key for found in certainties.values()}) == len(certainties)
        assert not set(certainties) & {found.voice for found in outcome.propositions}
        scores = [found.score for found in outcome.propositions]
        assert scores == sorted(scores, reverse=True)
        for found in [*certainties.values(), *outcome.propositions]:
            assert found.score == sum(WEIGHT[m.type] for m in found.indices)
            assert {m.name for m in found.indices} == {found.name}


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
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.ADDRESSING)]

    def test_a_first_name_leading_into_an_address(self):
        m = _mentions_in([utterance(0, 3, "Josiane, on a lu ensemble et tu nous diras")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.ADDRESSING)]

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
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.REFERRAL)]

    def test_an_opening_of_a_sentence_is_not_a_first_name(self):
        """« Bref, tu vois… », « Après, on verra… »: nothing to keep."""
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

    def test_eight_letters_is_where_the_adverb_rule_starts(self):
        """"Vraiment" has eight letters and is dropped; "Clément" has seven and stays."""
        assert _mentions_in([utterance(0, 3, "Vraiment, tu crois ?")]) == []
        kept = _mentions_in([utterance(0, 3, "Clément, tu crois ?")])
        assert [m.name for m in kept] == ["Clément"]

    def test_an_adverb_opening_the_sentence_does_not_hide_the_name_after_it(self):
        mentions = _mentions_in([utterance(0, 4, "Vraiment, tu as raison. Marc, on t'écoute.")])
        assert [(m.name, m.type) for m in mentions] == [("Marc", MentionKind.ADDRESSING)]


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
        assert outcome.certainties == {}

    def test_but_the_name_is_still_offered(self):
        # Proposing keeps the information without presenting it as settled: it is
        # for the user to settle, by listening ten seconds.
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
        assert outcome.certainties["v2"].name == "Sandy"

    def test_introducing_oneself_is_always_enough_alone(self):
        # The person names themselves: there is nothing speculative in that.
        utterances = [utterance(0, 4, "Bonjour, moi c'est Jacques, je commence.")]
        turns = [turn(0, 20, "v1")]
        outcome = attribute(_mentions_in(utterances), turns)
        assert outcome.certainties["v1"].name == "Jacques"


class TestJoiningNamesakesAfterTheMeeting:
    """Two voices given the same name are the same person.

    Measured on a real meeting of one hour forty-two: the chain concluded "Lise"
    on nine distinct voices, eight of them of a single turn. The minutes therefore
    announced eight participants too many. The same rule had existed for the live
    thread since that morning; the after-meeting chain lacked it.
    """

    def test_nine_voices_of_one_name_make_one(self) -> None:
        names = {f"v{i}": "Lise" for i in range(9)}
        weight = {f"v{i}": float(i) for i in range(9)}
        membership = join_namesakes(names, weight)
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

    def test_a_name_carried_by_one_voice_does_not_stop_the_namesakes_after_it(self) -> None:
        names = {"v1": "Pascal", "v2": "Lise", "v3": "Lise"}
        membership = join_namesakes(names, {"v1": 1.0, "v2": 2.0, "v3": 3.0})
        assert membership == {"v1": "v1", "v2": "v3", "v3": "v3"}

    def test_case_and_accents_do_not_make_two_people(self) -> None:
        names = {"v1": "Hélène", "v2": "helene", "v3": "HÉLÈNE"}
        membership = join_namesakes(names, {"v1": 5.0, "v2": 9.0, "v3": 1.0})
        assert set(membership.values()) == {"v2"}

    def test_a_voice_with_no_known_weight_breaks_nothing(self) -> None:
        names = {"v1": "Lise", "v2": "Lise"}
        membership = join_namesakes(names, {})
        assert len(set(membership.values())) == 1

    def test_a_voice_the_caller_did_not_weigh_counts_for_nothing(self) -> None:
        """Half a second measured outranks a voice with no measure at all."""
        membership = join_namesakes({"v1": "Lise", "v2": "Lise"}, {"v1": 0.5})
        assert set(membership.values()) == {"v1"}

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

    def test_an_exact_tie_goes_the_same_way_whatever_the_order(self) -> None:
        """Equal weights settle on the greater identifier, not on dict order.

        Two callers apply this rule, the chain after a run and the review of a
        kept meeting; they must agree on who keeps the name without either
        having to know how the other orders its voices.
        """
        forwards = join_namesakes({"v1": "Lise", "v2": "Lise"}, {"v1": 7.0, "v2": 7.0})
        backwards = join_namesakes({"v2": "Lise", "v1": "Lise"}, {"v2": 7.0, "v1": 7.0})
        assert set(forwards.values()) == {"v2"}
        assert backwards == forwards

    @given(
        st.dictionaries(
            st.sampled_from(["v0", "v1", "v2", "v3", "v4", "v5"]),
            st.sampled_from(["Lise", "lise", " LISE ", "Hélène", "Helene", "Pascal", "", "  "]),
            max_size=6,
        ),
        st.dictionaries(
            st.sampled_from(["v0", "v1", "v2", "v3", "v4", "v5"]),
            st.floats(min_value=0.0, max_value=600.0),
            max_size=6,
        ),
    )
    def test_every_group_rallies_to_its_heaviest_voice(self, names, weight) -> None:
        membership = join_namesakes(names, weight)
        assert set(membership) == set(names)
        for voice, kept in membership.items():
            assert kept in names
            if folded(names[voice]):
                assert folded(names[kept]) == folded(names[voice])
            else:
                assert kept == voice
            assert weight.get(kept, 0.0) >= weight.get(voice, 0.0)
        for one, other in [(a, b) for a in names for b in names if a < b]:
            if folded(names[one]) and folded(names[one]) == folded(names[other]):
                assert membership[one] == membership[other]
