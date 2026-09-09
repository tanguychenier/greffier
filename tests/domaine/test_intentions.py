"""Reconnaître, dans une phrase ordinaire, une demande d'apprendre.

Alimenter le contexte demandait d'ouvrir un fichier. Ces tests protègent les
deux moitiés du problème : comprendre ce qui doit être compris, et **ne pas**
comprendre ce qui n'en est pas.
"""

import pytest

from greffier.domaine.intentions import Apprentissage, Quoi, accord, comprendre


class TestCeQuiEstCompris:
    def test_un_sigle_avec_son_sens(self):
        appris = comprendre("retiens que OTP veut dire mot de passe à usage unique")
        assert appris is not None
        assert appris.quoi is Quoi.TERME
        assert appris.sujet == "OTP"
        assert appris.precision == "mot de passe à usage unique"

    def test_la_forme_avec_un_signe_egal(self):
        appris = comprendre("retiens : CASA = la plateforme de gestion des logements")
        assert appris is not None
        assert appris.sujet == "CASA"
        assert "plateforme" in appris.precision

    def test_un_terme_sans_sens(self):
        """« retiens le sigle FAST » : l'orthographe seule sert la transcription."""
        appris = comprendre("retiens le sigle FAST")
        assert appris is not None
        assert appris.sujet == "FAST"
        assert appris.precision == ""

    def test_une_personne_et_son_role(self):
        appris = comprendre("note que Maud est cheffe de projet Oasis")
        assert appris is not None
        assert appris.quoi is Quoi.PERSONNE
        assert appris.sujet == "Maud"
        assert "cheffe de projet" in appris.precision

    def test_un_nom_et_un_prenom(self):
        appris = comprendre("retiens que Pascal Berthier est développeur")
        assert appris is not None
        assert appris.sujet == "Pascal Berthier"

    def test_plusieurs_verbes_conviennent(self):
        for verbe in ("retiens", "note", "apprends", "garde"):
            assert comprendre(f"{verbe} que XYZ signifie quelque chose") is not None


class TestCeQuiNeDoitPasEtreCompris:
    """Un faux positif coûte une question, mais une entrée bancale dans le
    contexte pollue l'amorce de toutes les réunions suivantes."""

    def test_une_question_ordinaire(self):
        assert comprendre("qu'a-t-on décidé sur Oasis ?") is None

    def test_une_demande_de_definition_n_est_pas_une_definition(self):
        """« OTP c'est quoi ? » demande, il n'apprend pas."""
        assert comprendre("OTP c'est quoi ?") is None

    def test_un_fait_qui_n_est_pas_un_terme(self):
        assert comprendre("retiens que la réunion de jeudi est annulée") is None

    def test_un_etat_passager_n_est_pas_un_role(self):
        """« Sophie est en congé » ne décrit pas une fonction."""
        assert comprendre("retiens que Sophie est en congé") is None

    def test_une_phrase_trop_longue_comme_sujet_est_refusee(self):
        """Plus de cinq mots n'est pas un terme : c'est qu'on a mal découpé."""
        assert comprendre(
            "retiens que le processus complet de validation des dossiers "
            "signifie autre chose"
        ) is None

    def test_une_phrase_sans_verbe_d_apprentissage(self):
        assert comprendre("OTP veut dire mot de passe à usage unique") is None


class TestLaConfirmation:
    """On propose et on n'écrit pas : la phrase doit montrer ce qui sera écrit."""

    def test_elle_montre_le_terme_et_son_sens(self):
        phrase = comprendre("retiens que OTP veut dire mot de passe").dire()
        assert "OTP" in phrase
        assert "mot de passe" in phrase
        assert "Confirme" in phrase

    def test_elle_distingue_une_personne(self):
        phrase = comprendre("note que Maud est cheffe de projet").dire()
        assert "personnes du contexte" in phrase

    def test_un_apprentissage_sans_sujet_est_refuse(self):
        with pytest.raises(ValueError, match="sans sujet"):
            Apprentissage(Quoi.TERME, "   ")


class TestAccord:
    """Confirmer ou refuser, et distinguer les deux d'une nouvelle demande."""

    def test_oui_confirme(self):
        assert accord("oui") is True
        assert accord("Oui.") is True
        assert accord("c'est ça") is True

    def test_non_refuse(self):
        assert accord("non") is False
        assert accord("laisse tomber") is False

    def test_autre_chose_n_est_ni_l_un_ni_l_autre(self):
        """La prendre pour un refus perdrait la demande."""
        assert accord("et qu'a-t-on décidé sur Oasis ?") is None
        assert accord("retiens que FAST est un formulaire") is None

    def test_la_ponctuation_ne_change_rien(self):
        assert accord("oui !") is True

