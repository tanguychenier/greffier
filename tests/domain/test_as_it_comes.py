"""The words of an answer, cut at the sentences already finished."""

from greffier.domain.as_it_comes import SentencesAsTheyCome


class TestCuttingAsTheWordsCome:
    def test_nothing_is_handed_out_before_a_sentence_ends(self):
        cutter = SentencesAsTheyCome()
        assert cutter.take("Définissez d") == []
        assert cutter.take("'abord des critères") == []

    def test_a_sentence_is_handed_out_once_the_next_one_starts(self):
        cutter = SentencesAsTheyCome()
        assert cutter.take("Définissez des critères. Prévo") == ["Définissez des critères."]
        assert cutter.pending == "Prévo"

    def test_a_full_stop_at_the_very_end_waits_for_what_follows(self):
        # « 3. » may be the start of « 3.5 »: not a sentence until a space
        # follows the stop.
        cutter = SentencesAsTheyCome()
        assert cutter.take("Le budget est de 3.") == []
        assert cutter.take("5 millions. Voilà.") == ["Le budget est de 3.5 millions."]

    def test_several_sentences_in_one_take(self):
        cutter = SentencesAsTheyCome()
        assert cutter.take("Oui. Non ! Peut-être… Et ") == ["Oui.", "Non !", "Peut-être…"]

    def test_the_end_hands_out_what_is_left(self):
        cutter = SentencesAsTheyCome()
        cutter.take("Une phrase. Une autre sans point")
        assert cutter.finish() == ["Une autre sans point"]
        assert cutter.finish() == []

    def test_the_end_of_an_empty_answer_is_nothing(self):
        assert SentencesAsTheyCome().finish() == []
