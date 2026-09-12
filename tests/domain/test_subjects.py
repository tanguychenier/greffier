"""Reconnaître de quel sujet on parle, la difficulté réelle."""

import pytest

from greffier.domain.subjects import MENTIONS_MINIMALES, Registry, Subject


class TestASubjectAndTheNamesItGoesBy:
    def test_a_subject_with_no_name_is_refused(self):
        with pytest.raises(ValueError, match="sans nom"):
            Subject("  ")

    def test_it_is_recognised_under_its_name(self):
        assert Subject("Oasis").recognises("oasis") is True

    def test_it_is_recognised_under_its_aliases(self):
        """Personne ne peut deviner qu'« esup-oasis » désigne « Oasis »."""
        subject = Subject("Oasis", ("esup-oasis",))
        assert subject.recognises("esup oasis") is True

    def test_it_is_not_recognised_elsewhere(self):
        assert Subject("Oasis").recognises("Copernic") is False


class TestCountingTheMentions:
    def test_all_the_names_count_together(self):
        """C'est tout l'intérêt du registre."""
        registre = Registry([Subject("Oasis", ("esup-oasis",))])
        comptes = registre.count_them("On parle d'Oasis, puis d'esup-oasis, puis d'Oasis.")
        assert comptes == {"Oasis": 3}

    def test_the_count_ignores_case_and_accents(self):
        registre = Registry([Subject("recette")])
        assert registre.count_them("La Recette, la recette, la RECETTE") == {"recette": 3}

    def test_an_absent_subject_does_not_appear(self):
        assert Registry([Subject("Oasis")]).count_them("On parle d'autre chose.") == {}

    def test_a_longer_word_does_not_count(self):
        """« prod » ne doit pas se compter dans « production »."""
        assert Registry([Subject("prod")]).count_them("la production tourne") == {}

    def test_an_alias_holding_the_name_does_not_count_twice(self):
        """« esup-oasis » contient « oasis » : c'est une mention, pas deux.

        Additionner les occurrences de chaque appellation faisait de trois
        mentions d'Oasis quatre.
        """
        registre = Registry([Subject("Oasis", ("esup-oasis",))])
        assert registre.count_them("Oasis, puis esup-oasis, puis Oasis") == {"Oasis": 3}

    def test_the_longest_name_wins(self):
        registre = Registry([Subject("Oasis", ("esup-oasis",))])
        assert registre.count_them("On parle d'esup-oasis") == {"Oasis": 1}


class TestTheSubjectsKept:
    def test_the_subjects_come_out_most_present_first(self):
        registre = Registry([Subject("Oasis"), Subject("recette")])
        text = "Oasis " * 10 + "recette " * 4
        assert registre.subjects_of(text) == ["Oasis", "recette"]

    def test_a_passing_mention_is_not_a_subject(self):
        """Ouvrir une carte pour chaque allusion la remplirait de bruit."""
        registre = Registry([Subject("Docker")])
        assert registre.subjects_of("On a parlé de Docker une fois.") == []

    def test_the_threshold_stays_low_but_not_zero(self):
        assert 1 < MENTIONS_MINIMALES <= 5

    def test_the_threshold_is_a_setting(self):
        registre = Registry([Subject("Docker")])
        assert registre.subjects_of("Docker une fois.", minimum=1) == ["Docker"]


class TestFindingASubject:
    def test_by_its_name(self):
        registre = Registry([Subject("Oasis", board="uXjV1=")])
        found = registre.by_name("Oasis")
        assert found is not None and found.board == "uXjV1="

    def test_by_an_alias(self):
        registre = Registry([Subject("Oasis", ("esup-oasis",), board="uXjV1=")])
        found = registre.by_name("esup-oasis")
        assert found is not None and found.board == "uXjV1="

    def test_an_unknown_subject_returns_nothing(self):
        assert Registry([Subject("Oasis")]).by_name("Copernic") is None
