"""Recognising, in an ordinary sentence, a request to learn something.

Feeding the context took opening a file. These tests guard both halves of the
problem: understanding what has to be understood, and **not** understanding
what is not one.
"""

import pytest

from greffier.domain.intents import Learning, What, agreement, understand


class TestWhatIsUnderstood:
    def test_an_acronym_with_its_meaning(self):
        learned = understand("retiens que OTP veut dire mot de passe à usage unique")
        assert learned is not None
        assert learned.what is What.TERM
        assert learned.subject == "OTP"
        assert learned.precision == "mot de passe à usage unique"

    def test_the_form_with_an_equals_sign(self):
        learned = understand("retiens : CASA = la plateforme de gestion des logements")
        assert learned is not None
        assert learned.subject == "CASA"
        assert "plateforme" in learned.precision

    def test_a_term_without_a_meaning(self):
        """« retiens le sigle FAST »: the spelling alone serves the transcription."""
        learned = understand("retiens le sigle FAST")
        assert learned is not None
        assert learned.subject == "FAST"
        assert learned.precision == ""

    def test_a_person_and_their_role(self):
        learned = understand("note que Maud est cheffe de projet Oasis")
        assert learned is not None
        assert learned.what is What.NOBODY
        assert learned.subject == "Maud"
        assert "cheffe de projet" in learned.precision

    def test_a_surname_and_a_first_name(self):
        learned = understand("retiens que Pascal Berthier est développeur")
        assert learned is not None
        assert learned.subject == "Pascal Berthier"

    def test_several_verbs_will_do(self):
        for verb in ("retiens", "note", "apprends", "garde"):
            assert understand(f"{verb} que XYZ signifie quelque chose") is not None

    def test_a_term_of_five_words_is_still_a_term(self):
        """Five words pass and six do not: the cut is on the term's length."""
        learned = understand(
            "retiens que mise en production de nuit signifie le déploiement du soir"
        )
        assert learned is not None
        assert learned.subject == "mise en production de nuit"

    def test_the_quotes_around_a_term_are_not_part_of_it(self):
        learned = understand("retiens que « OTP » veut dire mot de passe à usage unique")
        assert learned is not None
        assert learned.subject == "OTP"

    def test_an_acronym_ending_in_x_keeps_its_last_letter(self):
        learned = understand("retiens que UX veut dire expérience utilisateur")
        assert learned is not None
        assert learned.subject == "UX"

    def test_the_article_before_a_term_goes_whatever_its_case(self):
        learned = understand("retiens : Les ANO = les anomalies remontées par le client")
        assert learned is not None
        assert learned.subject == "ANO"
        assert learned.precision == "anomalies remontées par le client"

    def test_a_question_mark_after_the_term_is_not_part_of_it(self):
        """The transcriber hears a rising voice and writes one."""
        learned = understand("retiens le sigle FAST ?")
        assert learned is not None
        assert learned.subject == "FAST"

    def test_a_person_given_with_an_equals_sign_is_still_a_person(self):
        learned = understand("retiens : Maud = cheffe de projet Oasis")
        assert learned is not None
        assert learned.what is What.NOBODY


class TestWhatMustNotBeUnderstood:
    """A false positive costs a question, but a shaky entry in the context pollutes
    the prompt seed of every meeting that follows.
    """

    def test_an_ordinary_question(self):
        assert understand("qu'a-t-on décidé sur Oasis ?") is None

    def test_asking_for_a_definition_is_not_one(self):
        """« OTP c'est quoi ? » asks, it does not teach."""
        assert understand("OTP c'est quoi ?") is None

    def test_a_fact_that_is_not_a_term(self):
        assert understand("retiens que la réunion de jeudi est annulée") is None

    def test_a_passing_state_is_not_a_role(self):
        """"Sophie est en congé" does not describe a function."""
        assert understand("retiens que Sophie est en congé") is None

    def test_too_long_a_sentence_as_a_subject_is_refused(self):
        """More than five words is not a term: the cut was wrong."""
        assert understand(
            "retiens que le processus complet de validation des dossiers "
            "signifie autre chose"
        ) is None

    def test_a_sentence_with_no_verb_of_learning(self):
        assert understand("OTP veut dire mot de passe à usage unique") is None


class TestTheConfirmation:
    """It offers and does not write: the sentence has to show what will be written."""

    def test_it_shows_the_term_and_its_meaning(self):
        sentence = understand("retiens que OTP veut dire mot de passe").say()
        assert "OTP" in sentence
        assert "mot de passe" in sentence
        assert "Confirme" in sentence

    def test_it_tells_a_person_apart(self):
        sentence = understand("note que Maud est cheffe de projet").say()
        assert "personnes du contexte" in sentence

    def test_learning_with_no_subject_is_refused(self):
        with pytest.raises(ValueError, match=r"^un apprentissage sans sujet ne sert à rien$"):
            Learning(What.TERM, "   ")

    def test_a_term_and_its_meaning_are_spelled_out_as_they_will_be_written(self):
        assert Learning(What.TERM, "OTP", "mot de passe à usage unique").say() == (
            "J'ajoute « OTP » (mot de passe à usage unique) au contexte. Confirme ?"
        )

    def test_a_term_without_a_meaning_is_offered_bare(self):
        assert Learning(What.TERM, "FAST").say() == "J'ajoute « FAST » au contexte. Confirme ?"

    def test_a_person_and_their_role_are_spelled_out(self):
        assert Learning(What.NOBODY, "Maud", "cheffe de projet").say() == (
            "J'ajoute « Maud », cheffe de projet aux personnes du contexte. Confirme ?"
        )

    def test_a_person_without_a_role_is_offered_by_name_alone(self):
        assert Learning(What.NOBODY, "Maud").say() == (
            "J'ajoute « Maud » aux personnes du contexte. Confirme ?"
        )


class TestYesOrNo:
    """Confirming or refusing, and telling both from a fresh request."""

    def test_yes_confirms(self):
        assert agreement("oui") is True
        assert agreement("Oui.") is True
        assert agreement("c'est ça") is True

    def test_no_refuses(self):
        assert agreement("non") is False
        assert agreement("laisse tomber") is False

    def test_anything_else_is_neither(self):
        """Taking it for a refusal would lose the request."""
        assert agreement("et qu'a-t-on décidé sur Oasis ?") is None
        assert agreement("retiens que FAST est un formulaire") is None

    def test_punctuation_changes_nothing(self):
        assert agreement("oui !") is True

