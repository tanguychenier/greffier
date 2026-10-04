"""The credits the model invents, and what has to stay.

Seen in a real thread on 2026-09-02: "(sous titré réalisé par… )" shown as a
turn of speech. Whisper was trained on subtitled videos and fills silences with
what it has seen most.
"""

from itertools import groupby

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.boilerplate import collapse_loops, is_an_annotation, is_boilerplate
from greffier.domain.models import Span, Utterance
from greffier.domain.profiles.french import FRENCH


class TestWhatIsDropped:
    @pytest.mark.parametrize("text", [
        "Sous-titrage réalisé par la communauté d'Amara.org",
        "sous-titrage réalisé par",
        "Sous-titres réalisés par la communauté",
        "Merci d'avoir regardé cette vidéo !",
        "MERCI D'AVOIR REGARDÉ CETTE VIDÉO",
        "Abonnez-vous !",
        "Sous-titrage Société Radio-Canada",
        "  Sous-titrage.  ",
    ])
    def test_a_whole_credits_line_goes(self, text):
        assert is_boilerplate(text, FRENCH)


class TestWhatStays:
    @pytest.mark.parametrize("text", [
        "Merci.",
        "Merci Sophie, on valide jeudi.",
        "On a sous-titré la vidéo de présentation, c'est fait.",
        "Abonnez-vous à la liste de diffusion du projet, je vous envoie le lien.",
        "",
        "   ",
    ])
    def test_real_speech_stays(self, text):
        """Better to let a credit through than to lose a decision."""
        assert not is_boilerplate(text, FRENCH)

    @pytest.mark.parametrize("text", [
        "Merci d'avoir regardé le ticket, il est passé en recette.",
        "Merci d'avoir regardé cette vidéo, mais revenons au calendrier de la "
        "recette : il faut trancher avant jeudi.",
        "Sous-titrage réalisé par nos soins, et validé par la communication.",
    ])
    def test_a_sentence_that_starts_like_a_credit_but_goes_on(self, text):
        """The trap of matching on a prefix: that sentence disappeared, when it carries
        information.
        """
        assert not is_boilerplate(text, FRENCH)


class TestAnnotations:
    """What the model writes when it hears sound without speech.

    Taken from the thread of a real meeting: "*Belouge*" recorded as a turn of
    speech, with a voiceprint of its own, and therefore one more voice in a meeting
    that held only a few.
    """

    def test_an_annotation_between_asterisks_goes(self):
        assert is_an_annotation("*Belouge*")

    def test_an_annotation_between_brackets_goes(self):
        assert is_an_annotation("(rires)")
        assert is_an_annotation("[Applaudissements]")

    def test_a_music_note_goes(self):
        assert is_an_annotation("♪ ♪ ♪")

    def test_a_bracket_inside_a_sentence_stays(self):
        """Couper là perdrait la phrase."""
        assert not is_an_annotation("il a dit (à tort) que c'était prêt")

    def test_two_annotations_in_a_sentence_do_not_make_it_one(self):
        assert not is_an_annotation("(a) et (b) sont prêts")

    def test_an_ordinary_sentence_stays(self):
        assert not is_an_annotation("on reprend le sujet lundi")

    def test_a_text_too_short_triggers_nothing(self):
        assert not is_an_annotation("**")

    def test_three_characters_are_enough_for_an_annotation(self):
        """The shortest ones the model writes: notes alone, a silence between brackets."""
        assert is_an_annotation("♪♪♪")
        assert is_an_annotation("(…)")

    def test_a_bracket_opened_or_closed_alone_is_speech(self):
        """The transcriber sometimes loses one half of a pair; the words are still words."""
        assert not is_an_annotation("(inaudible, il reprend le sujet lundi")
        assert not is_an_annotation("il reprend le sujet lundi)")

    def test_a_word_between_two_annotations_keeps_the_line(self):
        assert not is_an_annotation("(inaudible) oui (rires)")



@st.composite
def abutting_utterances(draw) -> list[Utterance]:
    """Up to twelve one-second turns, each starting where the last one ended."""
    texts = draw(st.lists(st.sampled_from(["oui", "tu m'entends ?", "voilà"]), max_size=12))
    return [Utterance(span=Span(float(i), float(i + 1)), text=text)
            for i, text in enumerate(texts)]


class TestTheTranscriberLoop:
    """Eleven times the same sentence in a row is the model, not a person.

    Measured on the meeting of 2026-09-10 at 13:08: "Est-ce que tu entends
    Lucie ?" written down **eleven times**, in eleven consecutive one-second turns,
    with three other loops beside it. Of the hundred and twenty-five turns in the
    thread, sixty-five were repetition. Whisper does this on near-silence.
    """

    def _loop(self, how_many: int, text: str = "Est-ce que tu entends Lucie ?"):
        return [
            Utterance(span=Span(30.0 + i, 31.0 + i), text=text)
            for i in range(how_many)
        ]

    def test_eleven_repeats_become_one(self):
        assert len(collapse_loops(self._loop(11))) == 1

    def test_the_kept_sentence_covers_the_whole_run(self):
        """The passage did last eleven seconds: the timestamp must say so."""
        kept_one = collapse_loops(self._loop(11))[0]
        assert (kept_one.span.start, kept_one.span.end) == (30.0, 41.0)

    def test_twice_in_a_row_is_a_person(self):
        """Somebody repeats themselves, or two slices overlap. Left untouched."""
        assert len(collapse_loops(self._loop(2))) == 2

    def test_three_times_is_a_loop(self):
        assert len(collapse_loops(self._loop(3))) == 1

    def test_a_breath_breaks_the_loop(self):
        """Someone asking their question again leaves a breath.

        Three segments glued together fold up; the one arriving after the silence
        stays a sentence of its own, because it was said on its own.
        """
        said_ones = [
            Utterance(span=Span(0.0, 1.0), text="tu m'entends ?"),
            Utterance(span=Span(1.0, 2.0), text="tu m'entends ?"),
            Utterance(span=Span(2.0, 3.0), text="tu m'entends ?"),
            Utterance(span=Span(9.0, 10.0), text="tu m'entends ?"),
        ]
        kept_ones = collapse_loops(said_ones)
        assert len(kept_ones) == 2
        assert (kept_ones[0].span.start, kept_ones[0].span.end) == (0.0, 3.0)
        assert kept_ones[1].span.start == 9.0

    def test_two_loops_in_a_row_are_two_sentences(self):
        said_ones = self._loop(4) + [
            Utterance(span=Span(34.0 + i, 35.0 + i), text="Je vais vous créer la vache.")
            for i in range(4)
        ]
        kept_ones = collapse_loops(said_ones)
        assert len(kept_ones) == 2
        assert kept_ones[0].text != kept_ones[1].text

    def test_case_and_accents_do_not_make_two_sentences(self):
        said_ones = [
            Utterance(span=Span(0.0, 1.0), text="Voilà."),
            Utterance(span=Span(1.0, 2.0), text="voila"),
            Utterance(span=Span(2.0, 3.0), text="VOILÀ !"),
        ]
        assert len(collapse_loops(said_ones)) == 1

    def test_an_ordinary_conversation_is_untouched(self):
        said_ones = [
            Utterance(span=Span(0.0, 3.0), text="on cale la recette jeudi"),
            Utterance(span=Span(3.0, 6.0), text="d'accord, je prévois les tests"),
            Utterance(span=Span(6.0, 9.0), text="et la mise en prod lundi"),
        ]
        assert collapse_loops(said_ones) == said_ones

    def test_an_empty_or_short_list_breaks_nothing(self):
        assert collapse_loops([]) == []
        assert len(collapse_loops(self._loop(1))) == 1

    def test_a_silence_exactly_at_the_tolerance_still_glues_the_run(self):
        said_ones = [
            Utterance(span=Span(0.0, 1.0), text="tu m'entends ?"),
            Utterance(span=Span(1.5, 2.5), text="tu m'entends ?"),
            Utterance(span=Span(3.0, 4.0), text="tu m'entends ?"),
        ]
        assert len(collapse_loops(said_ones, gap=0.5)) == 1
        assert len(collapse_loops(said_ones, gap=0.49)) == 3

    def test_twice_in_a_row_after_another_sentence_is_still_a_person(self):
        said_ones = [
            Utterance(span=Span(0.0, 1.0), text="on commence ?"),
            Utterance(span=Span(1.0, 2.0), text="tu m'entends ?"),
            Utterance(span=Span(2.0, 3.0), text="tu m'entends ?"),
        ]
        assert collapse_loops(said_ones) == said_ones

    def test_a_sentence_in_between_breaks_the_run(self):
        """A question, an answer, the question twice more: four sentences, no loop."""
        said_ones = [
            Utterance(span=Span(0.0, 1.0), text="tu m'entends ?"),
            Utterance(span=Span(1.0, 2.0), text="oui"),
            Utterance(span=Span(2.0, 3.0), text="tu m'entends ?"),
            Utterance(span=Span(3.0, 4.0), text="tu m'entends ?"),
        ]
        assert collapse_loops(said_ones) == said_ones

    @given(abutting_utterances(), st.integers(min_value=2, max_value=5))
    def test_a_run_long_enough_folds_over_its_span_and_a_shorter_one_stays_whole(
        self, said_ones, repeats,
    ):
        expected: list[Utterance] = []
        for _, same in groupby(said_ones, key=lambda u: u.text):
            run = list(same)
            if len(run) >= repeats:
                expected.append(Utterance(span=Span(run[0].span.start, run[-1].span.end),
                                          text=run[0].text))
            else:
                expected.extend(run)
        assert collapse_loops(said_ones, repeats) == expected
