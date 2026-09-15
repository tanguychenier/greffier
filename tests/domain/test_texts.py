"""What stands as an identifier when reducing to ASCII leaves nothing.

Three places reduce free text to a file identifier: the voice bank, a
meeting's name, the anchor of an email section. All three fell back on a fixed
word when nothing was left: « sans-nom », « reunion », « s- », hence on the
SAME identifier for different texts. In the voice bank, that merged two
people.
"""

from greffier.domain.texts import short_voiceprint


class TestAShortFingerprint:
    def test_two_different_texts_are_not_confused(self):
        assert short_voiceprint("Дмитрий") != short_voiceprint("Ольга")

    def test_the_same_text_always_returns_the_same(self):
        """A voice named today has to be found tomorrow: « hash », for its
        part, changes from one run to the next."""
        assert short_voiceprint("田中") == short_voiceprint("田中")

    def test_it_fits_in_a_file_name(self):
        voiceprint = short_voiceprint("Δημήτρης")
        assert len(voiceprint) == 10
        assert voiceprint.isalnum()

    def test_the_empty_string_has_one_too(self):
        """A title made entirely of punctuation is not an error."""
        assert short_voiceprint("")
