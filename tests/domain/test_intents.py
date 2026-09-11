"""Reconnaître, dans une phrase ordinaire, une demande d'apprendre.

Alimenter le contexte demandait d'ouvrir un fichier. Ces tests protègent les
deux moitiés du problème : comprendre ce qui doit être compris, et **ne pas**
comprendre ce qui n'en est pas.
"""

import pytest

from greffier.domain.intents import Learning, What, agreement, understand


class TestWhatIsUnderstood:
    def test_an_acronym_with_its_meaning(self):
        appris = understand("retiens que OTP veut dire mot de passe à usage unique")
        assert appris is not None
        assert appris.what is What.TERME
        assert appris.subject == "OTP"
        assert appris.precision == "mot de passe à usage unique"

    def test_the_form_with_an_equals_sign(self):
        appris = understand("retiens : CASA = la plateforme de gestion des logements")
        assert appris is not None
        assert appris.subject == "CASA"
        assert "plateforme" in appris.precision

    def test_a_term_without_a_meaning(self):
        """« retiens le sigle FAST » : l'orthographe seule sert la transcription."""
        appris = understand("retiens le sigle FAST")
        assert appris is not None
        assert appris.subject == "FAST"
        assert appris.precision == ""

    def test_a_person_and_their_role(self):
        appris = understand("note que Maud est cheffe de projet Oasis")
        assert appris is not None
        assert appris.what is What.NOBODY
        assert appris.subject == "Maud"
        assert "cheffe de projet" in appris.precision

    def test_a_surname_and_a_first_name(self):
        appris = understand("retiens que Pascal Berthier est développeur")
        assert appris is not None
        assert appris.subject == "Pascal Berthier"

    def test_several_verbs_will_do(self):
        for verbe in ("retiens", "note", "apprends", "garde"):
            assert understand(f"{verbe} que XYZ signifie quelque chose") is not None


class TestWhatMustNotBeUnderstood:
    """Un faux positif coûte une question, mais une entrée bancale dans le
    contexte pollue l'amorce de toutes les réunions suivantes."""

    def test_an_ordinary_question(self):
        assert understand("qu'a-t-on décidé sur Oasis ?") is None

    def test_asking_for_a_definition_is_not_one(self):
        """« OTP c'est quoi ? » demande, il n'apprend pas."""
        assert understand("OTP c'est quoi ?") is None

    def test_a_fact_that_is_not_a_term(self):
        assert understand("retiens que la réunion de jeudi est annulée") is None

    def test_a_passing_state_is_not_a_role(self):
        """« Sophie est en congé » ne décrit pas une fonction."""
        assert understand("retiens que Sophie est en congé") is None

    def test_too_long_a_sentence_as_a_subject_is_refused(self):
        """Plus de cinq mots n'est pas un terme : c'est qu'on a mal découpé."""
        assert understand(
            "retiens que le processus complet de validation des dossiers "
            "signifie autre chose"
        ) is None

    def test_a_sentence_with_no_verb_of_learning(self):
        assert understand("OTP veut dire mot de passe à usage unique") is None


class TestTheConfirmation:
    """On propose et on n'écrit pas : la phrase doit montrer ce qui sera écrit."""

    def test_it_shows_the_term_and_its_meaning(self):
        sentence = understand("retiens que OTP veut dire mot de passe").say()
        assert "OTP" in sentence
        assert "mot de passe" in sentence
        assert "Confirme" in sentence

    def test_it_tells_a_person_apart(self):
        sentence = understand("note que Maud est cheffe de projet").say()
        assert "personnes du contexte" in sentence

    def test_learning_with_no_subject_is_refused(self):
        with pytest.raises(ValueError, match="sans sujet"):
            Learning(What.TERME, "   ")


class TestYesOrNo:
    """Confirmer ou refuser, et distinguer les deux d'une nouvelle demande."""

    def test_yes_confirms(self):
        assert agreement("oui") is True
        assert agreement("Oui.") is True
        assert agreement("c'est ça") is True

    def test_no_refuses(self):
        assert agreement("non") is False
        assert agreement("laisse tomber") is False

    def test_anything_else_is_neither(self):
        """La prendre pour un refus perdrait la demande."""
        assert agreement("et qu'a-t-on décidé sur Oasis ?") is None
        assert agreement("retiens que FAST est un formulaire") is None

    def test_punctuation_changes_nothing(self):
        assert agreement("oui !") is True

