"""The credits the model invents, and what has to stay.

Seen in a real thread on 2026-09-02: "(sous titré réalisé par… )" shown as a
turn of speech. Whisper was trained on subtitled videos and fills silences with
what it has seen most.
"""

import pytest

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



class TestTheTranscriberLoop:
    """Eleven times the same sentence in a row is the model, not a person.

    Measured on the meeting of 2026-09-10 at 13:08: "Est-ce que tu entends
    Lucie ?" written down **eleven times**, in eleven consecutive one-second turns,
    with three other loops beside it. Of the hundred and twenty-five turns in the
    thread, sixty-five were repetition. Whisper does this on near-silence.
    """

    def _loop(self, how_many: int, texte: str = "Est-ce que tu entends Lucie ?"):
        return [
            Utterance(span=Span(30.0 + i, 31.0 + i), text=texte)
            for i in range(how_many)
        ]

    def test_eleven_repeats_become_one(self):
        assert len(collapse_loops(self._loop(11))) == 1

    def test_the_kept_sentence_covers_the_whole_run(self):
        """Le passage a bien duré onze secondes : l'horodatage doit le dire."""
        gardee = collapse_loops(self._loop(11))[0]
        assert (gardee.span.start, gardee.span.end) == (30.0, 41.0)

    def test_twice_in_a_row_is_a_person(self):
        """Quelqu'un se répète, ou deux tranches se recouvrent. On n'y touche pas."""
        assert len(collapse_loops(self._loop(2))) == 2

    def test_three_times_is_a_loop(self):
        assert len(collapse_loops(self._loop(3))) == 1

    def test_a_breath_breaks_the_loop(self):
        """Someone asking their question again leaves a breath.

        Three segments glued together fold up; the one arriving after the silence
        stays a sentence of its own, because it was said on its own.
        """
        dites = [
            Utterance(span=Span(0.0, 1.0), text="tu m'entends ?"),
            Utterance(span=Span(1.0, 2.0), text="tu m'entends ?"),
            Utterance(span=Span(2.0, 3.0), text="tu m'entends ?"),
            Utterance(span=Span(9.0, 10.0), text="tu m'entends ?"),
        ]
        gardees = collapse_loops(dites)
        assert len(gardees) == 2
        assert (gardees[0].span.start, gardees[0].span.end) == (0.0, 3.0)
        assert gardees[1].span.start == 9.0

    def test_two_loops_in_a_row_are_two_sentences(self):
        dites = self._loop(4) + [
            Utterance(span=Span(34.0 + i, 35.0 + i), text="Je vais vous créer la vache.")
            for i in range(4)
        ]
        gardees = collapse_loops(dites)
        assert len(gardees) == 2
        assert gardees[0].text != gardees[1].text

    def test_case_and_accents_do_not_make_two_sentences(self):
        dites = [
            Utterance(span=Span(0.0, 1.0), text="Voilà."),
            Utterance(span=Span(1.0, 2.0), text="voila"),
            Utterance(span=Span(2.0, 3.0), text="VOILÀ !"),
        ]
        assert len(collapse_loops(dites)) == 1

    def test_an_ordinary_conversation_is_untouched(self):
        dites = [
            Utterance(span=Span(0.0, 3.0), text="on cale la recette jeudi"),
            Utterance(span=Span(3.0, 6.0), text="d'accord, je prévois les tests"),
            Utterance(span=Span(6.0, 9.0), text="et la mise en prod lundi"),
        ]
        assert collapse_loops(dites) == dites

    def test_an_empty_or_short_list_breaks_nothing(self):
        assert collapse_loops([]) == []
        assert len(collapse_loops(self._loop(1))) == 1
