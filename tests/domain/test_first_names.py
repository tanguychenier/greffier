"""What may enter the bank under a person's name."""

import pytest

from greffier.domain.first_names import acceptable, normalise, refusal


class TestWhatIsAccepted:
    @pytest.mark.parametrize("name", [
        "Marcel", "Tanguy", "Anne-Sophie", "Jean Marcel", "Li", "Ólafur",
        "Nguyễn", "O'Connor", "Zoé",
    ])
    def test_a_first_name_is_accepted(self, name):
        assert acceptable(name), refusal(name)


class TestWhatIsRefused:
    def test_a_label_of_the_window_is_refused(self):
        """The case measured: the machine's bank carried « A nommer ».

        It is what the « Nom » column shows for a voice that has none yet.
        Once in the bank, it is recognised at every following meeting.
        """
        assert not acceptable("A nommer")
        assert not acceptable("à nommer")
        assert "pas un prénom" in refusal("A nommer")

    @pytest.mark.parametrize("name", [
        "", "   ", "M", "?", "-", "Les autres", "inconnu", "Personne",
        "Voix 12", "Personne 3", "42", "...", "Sans nom",
    ])
    def test_what_is_not_a_first_name_is_refused(self, name):
        assert not acceptable(name)

    def test_a_whole_sentence_is_refused(self):
        assert not acceptable("je crois que c'était plutôt Marcel qui parlait là")

    def test_the_refusal_says_why(self):
        """A refusal without a reason has the same entry typed again."""
        assert refusal("") and refusal("M") and refusal("Voix 12")


class TestTidyingAName:
    def test_the_case_is_made_uniform(self):
        """Otherwise « marcel » and « Marcel » are two people in the bank,
        each with half of the voiceprints."""
        assert normalise("marcel") == "Marcel"

    def test_the_spaces_collapse(self):
        assert normalise("  Anne   Sophie ") == "Anne Sophie"

    def test_a_name_already_clean_does_not_move(self):
        assert normalise("Anne-Sophie") == "Anne-Sophie"

    def test_the_rest_of_the_name_keeps_its_case(self):
        assert normalise("McCarthy") == "McCarthy"
