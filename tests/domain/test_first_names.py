"""What may enter the bank under a person's name."""

import unicodedata

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greffier.domain.first_names import LABELS, LENGTH, acceptable, normalise, refusal

#: mutmut 3.8 runs pytest several times in one process, so Hypothesis sees the
#: second run's class instance as another executor and fails the health check
#: before any example runs. The profile's other settings are kept.
in_one_process = settings(suppress_health_check=[*settings.default.suppress_health_check,
                                                 HealthCheck.differing_executors])

#: What a first name is spelt with: letters, accented or not, nothing else.
LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZéèêëàâîïôûùçÉÀÇñõøå"


def folded(name: str) -> str:
    """Lower case without accents, the form the labels are compared in."""
    return "".join(c for c in unicodedata.normalize("NFD", name.lower())
                   if unicodedata.category(c) != "Mn")


#: A word of letters within the two lengths that does not spell a label of
#: the window, « Non » or « Voix » being words of letters too.
first_names = st.text(LETTERS, min_size=LENGTH[0], max_size=LENGTH[1]).filter(
    lambda name: folded(name) not in LABELS
)


class TestWhatIsAccepted:
    @pytest.mark.parametrize("name", [
        "Marcel", "Tanguy", "Anne-Sophie", "Jean Marcel", "Li", "Ólafur",
        "Nguyễn", "O'Connor", "Zoé",
    ])
    def test_a_first_name_is_accepted(self, name):
        assert acceptable(name), refusal(name)

    @in_one_process
    @given(first_names)
    def test_any_word_of_letters_within_the_lengths_is_accepted(self, name):
        assert refusal(name) == ""


class TestWhatIsRefused:
    def test_a_label_of_the_window_is_refused(self):
        """The case measured: the machine's bank carried « A nommer ».

        It is what the « Nom » column shows for a voice that has none yet.
        Once in the bank, it is recognised at every following meeting.
        """
        assert not acceptable("A nommer")
        assert not acceptable("à nommer")
        assert refusal("A nommer") == (
            "« A nommer » est ce que Greffier affiche quand une voix n'a pas "
            "encore de nom, pas un prénom. Une telle entrée en banque serait "
            "reconnue à chaque réunion suivante."
        )

    @pytest.mark.parametrize("label", sorted(LABELS))
    def test_every_label_is_refused_however_it_is_typed(self, label):
        """Capitals, a full stop after it, spaces around it: still the label."""
        for typed in (label, label.upper(), label.capitalize(), f"{label}.", f" {label} "):
            assert not acceptable(typed), typed

    @pytest.mark.parametrize("label", ["indeterminé", "Á nommer", "INDÉTERMINE"])
    def test_a_label_half_accented_is_still_the_label(self, label):
        assert not acceptable(label)

    @pytest.mark.parametrize("label", ["à nommer", "indéterminé"])
    def test_a_label_in_decomposed_unicode_is_still_the_label(self, label):
        """A macOS keyboard writes « à » as « a » plus a combining accent."""
        decomposed = unicodedata.normalize("NFD", label)
        assert decomposed != label
        assert not acceptable(decomposed)

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

    def test_nothing_typed_is_asked_for_a_first_name(self):
        assert refusal("") == "Saisis un prénom."
        assert refusal("   ") == "Saisis un prénom."

    @pytest.mark.parametrize("typed", ["Voix  12", "personne 3"])
    def test_a_numbered_label_names_itself_in_the_refusal(self, typed):
        """As typed, spaces collapsed, so the person sees what was refused."""
        shown = " ".join(typed.split())
        assert refusal(typed) == f"« {shown} » est une étiquette de Greffier, pas un prénom."

    @pytest.mark.parametrize("number", ["12", "#3", "4.", "007"])
    def test_a_bare_number_is_called_a_voice_number(self, number):
        """The sentence was written for this case and nobody ever read it: a
        name without a letter was refused one test earlier, with the generic
        reason, and the check for a voice number came after, unreachable."""
        assert refusal(number) == "Un numéro de voix n'est pas un prénom."

    def test_punctuation_alone_is_short_of_letters_not_a_number(self):
        assert refusal("...") == "Un prénom porte des lettres."
        assert refusal("---") == "Un prénom porte des lettres."


class TestHowLongAFirstNameIs:
    def test_two_letters_is_the_shortest(self):
        assert acceptable("Li")
        assert refusal("L") == "Un prénom fait au moins deux lettres."

    def test_thirty_letters_is_the_longest(self):
        longest = "Marie-Antoinette-Joséphine-Lou"
        assert len(longest) == LENGTH[1]
        assert acceptable(longest)
        assert refusal(longest + "p") == "C'est trop long pour un prénom."

    def test_the_spaces_around_do_not_count(self):
        assert acceptable("  Li  ")
        assert acceptable("  " + "Marie-Antoinette-Joséphine-Lou" + "  ")

    @in_one_process
    @given(st.text(LETTERS, min_size=LENGTH[1] + 1, max_size=2 * LENGTH[1]))
    def test_past_the_longest_it_is_too_long_whatever_it_spells(self, name):
        assert refusal(name) == "C'est trop long pour un prénom."


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

    def test_nothing_stays_nothing(self):
        assert normalise("") == ""
        assert normalise("   ") == ""

    @in_one_process
    @given(first_names)
    def test_only_the_first_letter_moves(self, name):
        tidy = normalise(name)
        assert tidy[0] == name[0].upper()
        assert tidy[1:] == name[1:]

    @in_one_process
    @given(first_names)
    def test_tidying_twice_is_tidying_once(self, name):
        """The bank reads names back and tidies them again on every save."""
        assert normalise(normalise(name)) == normalise(name)

    @in_one_process
    @given(first_names)
    def test_a_name_accepted_is_still_accepted_once_tidied(self, name):
        assert acceptable(normalise(name))
