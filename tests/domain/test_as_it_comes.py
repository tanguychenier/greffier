"""The words of an answer, cut at the sentences already finished."""

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.as_it_comes import SentencesAsTheyCome

#: What a model streams: words, the marks that end a sentence, and spaces.
streamed = st.text(alphabet="ab .!?…3", max_size=24)


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

    def test_after_several_sentences_only_the_unfinished_tail_waits(self):
        cutter = SentencesAsTheyCome()
        cutter.take("Oui. Non ! Peut-être… Et ")
        assert cutter.pending == "Et "
        assert cutter.take("voilà. ") == ["Et voilà."]

    @given(streamed, st.integers(min_value=0, max_value=24))
    def test_where_the_stream_is_cut_changes_nothing_to_the_sentences(self, text, at):
        """The model hands out its words in pieces of any size; the sentences
        read must be those of the whole answer."""
        in_one_go = SentencesAsTheyCome()
        in_two = SentencesAsTheyCome()
        whole = in_one_go.take(text) + in_one_go.finish()
        pieces = in_two.take(text[:at]) + in_two.take(text[at:]) + in_two.finish()
        assert pieces == whole

    def test_the_end_hands_out_what_is_left(self):
        cutter = SentencesAsTheyCome()
        cutter.take("Une phrase. Une autre sans point")
        assert cutter.finish() == ["Une autre sans point"]
        assert cutter.finish() == []

    def test_the_end_of_an_empty_answer_is_nothing(self):
        assert SentencesAsTheyCome().finish() == []
