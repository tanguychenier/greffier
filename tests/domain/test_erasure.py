"""Taking a name out of a text, and leaving the rest of it alone."""

from __future__ import annotations

import unicodedata

from greffier.domain.erasure import UNNAMED, count, redact, same_person, without_marks


class TestFindingTheNameAndNothingElse:
    def test_the_name_alone_is_replaced(self) -> None:
        texte, how_many = redact("Sophie prend la recette.", "Sophie")
        assert texte == f"{UNNAMED} prend la recette."
        assert how_many == 1

    def test_a_longer_word_starting_the_same_is_left_alone(self) -> None:
        # « Luc » must not eat « Lucie », nor the « luc » in « caduc ».
        texte, how_many = redact("Lucie trouve l'argument caduc.", "Luc")
        assert texte == "Lucie trouve l'argument caduc."
        assert how_many == 0

    def test_punctuation_is_a_boundary(self) -> None:
        texte, _ = redact("D'accord, Julie. Julie ?", "Julie")
        assert texte == f"D'accord, {UNNAMED}. {UNNAMED} ?"

    def test_the_case_does_not_matter(self) -> None:
        # Somebody typing in a hurry writes « sophie » in the bank.
        assert count("SOPHIE, sophie, Sophie", "Sophie") == 3

    def test_a_first_name_in_two_words_is_found(self) -> None:
        texte, how_many = redact("Marie  Dupont arrive.", "Marie Dupont")
        assert how_many == 1
        assert texte == f"{UNNAMED} arrive."


class TestWhateverAccentsItIsWrittenWith:
    def test_the_accent_in_the_text_and_not_in_the_name(self) -> None:
        assert count("Élodie relit.", "Elodie") == 1

    def test_the_accent_in_the_name_and_not_in_the_text(self) -> None:
        assert count("Elodie relit.", "Élodie") == 1

    def test_the_two_ways_macos_and_linux_write_the_same_accent(self) -> None:
        # macOS writes « é » as e + U+0301, Linux as one character. The same
        # person, and until this they were two.
        compose = unicodedata.normalize("NFC", "Élodie relit.")
        decompose = unicodedata.normalize("NFD", "Élodie relit.")
        assert compose != decompose
        assert count(compose, "Élodie") == count(decompose, "Élodie") == 1

    def test_marks_are_dropped_for_comparing_and_not_for_keeping(self) -> None:
        assert without_marks("Élodie") == "Elodie"
        texte, _ = redact("Écoute, Élodie.", "Élodie")
        assert texte.startswith("Écoute")


class TestLeavingATextAlone:
    def test_a_text_without_the_name_comes_back_character_for_character(self) -> None:
        # The comparison normalises; rewriting a file that has nothing to do
        # with the person would change its bytes for nothing.
        original = unicodedata.normalize("NFD", "Réunion du café, rien à voir.")
        texte, how_many = redact(original, "Sophie")
        assert how_many == 0
        assert texte == original

    def test_an_empty_name_erases_nothing(self) -> None:
        assert redact("Tout le monde est là.", "   ") == ("Tout le monde est là.", 0)
        assert count("Tout le monde est là.", "") == 0

    def test_a_replacement_of_one_s_own(self) -> None:
        texte, _ = redact("Sophie parle.", "Sophie", replacement="[effacé]")
        assert texte == "[effacé] parle."


class TestTwoSpellingsOfTheSamePerson:
    def test_accents_and_case_do_not_make_two_people(self) -> None:
        assert same_person("Élodie", "elodie")
        assert same_person(" Sophie ", "Sophie")

    def test_two_names_stay_two_people(self) -> None:
        assert not same_person("Sophie", "Sophia")
