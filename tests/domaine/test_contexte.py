"""Le contexte du milieu : ce qu'un modèle ne peut pas deviner."""

import pytest

from greffier.domaine.contexte import (
    AMORCE_MAXIMUM,
    Contexte,
    Intervenant,
    Terme,
)


class TestTerme:
    def test_un_sigle_porte_son_sens_pour_le_redacteur(self):
        assert Terme("OTP", "mot de passe à usage unique").glose == (
            "OTP (mot de passe à usage unique)"
        )

    def test_sans_sens_le_terme_reste_nu(self):
        assert Terme("CASA").glose == "CASA"

    def test_un_terme_sans_ecriture_est_refuse(self):
        with pytest.raises(ValueError, match="sans écriture"):
            Terme("   ")


class TestAmorce:
    """Ce qui décide de l'orthographe pendant la transcription.

    Mesuré le 2026-09-09 sur une réunion réelle : « déploiement » rendu
    « exploitement », « emploi du temps » rendu « emploi fictif ». Ces mots ne
    sont nulle part dans ce qu'un modèle a appris.
    """

    def test_les_termes_et_les_noms_y_figurent_ensemble(self):
        contexte = Contexte(
            termes=(Terme("CASA"),),
            intervenants=(Intervenant("Kerann"),),
        )
        amorce = contexte.amorce()
        assert "CASA" in amorce
        assert "Kerann" in amorce

    def test_le_sens_n_encombre_pas_l_amorce(self):
        """Le transcripteur ne raisonne pas : lui donner des définitions le noie."""
        amorce = Contexte(termes=(Terme("OTP", "mot de passe à usage unique"),)).amorce()
        assert "OTP" in amorce
        assert "usage unique" not in amorce

    def test_un_contexte_vide_ne_produit_aucune_amorce(self):
        assert Contexte().amorce() == ""

    def test_l_amorce_tient_dans_la_limite_du_modele(self):
        """whisper tronque au-delà de 224 jetons, sans prévenir."""
        contexte = Contexte(termes=tuple(Terme(f"terme-{n:03d}") for n in range(200)))
        assert len(contexte.amorce()) <= AMORCE_MAXIMUM

    def test_ce_qui_ne_tient_pas_est_dit(self):
        contexte = Contexte(termes=tuple(Terme(f"terme-{n:03d}") for n in range(200)))
        assert contexte.ecartes(), "il faut pouvoir avertir plutôt que tronquer en silence"

    def test_aucun_terme_n_est_coupe_en_deux(self):
        """Une écriture coupée apprend une orthographe fausse : pire que rien."""
        contexte = Contexte(termes=tuple(Terme(f"terme-{n:03d}") for n in range(200)))
        for mot in contexte.amorce().split("Vocabulaire : ")[1].rstrip(".").split(", "):
            assert mot.startswith("terme-") and len(mot) == len("terme-000")

    def test_un_terme_repete_ne_compte_qu_une_fois(self):
        amorce = Contexte(termes=(Terme("OTP"), Terme("OTP"))).amorce()
        assert amorce.count("OTP") == 1


class TestEntete:
    """Ce que le rédacteur reçoit : les écritures **et** leur sens."""

    def test_les_sens_sont_donnes_au_redacteur(self):
        entete = Contexte(termes=(Terme("OTP", "mot de passe à usage unique"),)).entete()
        assert "mot de passe à usage unique" in entete

    def test_le_redacteur_est_prie_de_ne_pas_reciter_le_glossaire(self):
        entete = Contexte(termes=(Terme("OTP"),)).entete()
        assert "que ceux dont il est question" in entete

    def test_un_role_n_autorise_pas_a_preter_une_position(self):
        entete = Contexte(intervenants=(Intervenant("Sophie", "cheffe de projet"),)).entete()
        assert "jamais d'après son rôle" in entete

    def test_un_contexte_vide_ne_dit_rien(self):
        assert Contexte().entete() == ""


class TestFusion:
    """Le contexte du poste, complété par celui d'une réunion précise."""

    def test_le_plus_precis_l_emporte(self):
        general = Contexte(termes=(Terme("OTP", "ancien sens"),))
        precis = Contexte(termes=(Terme("OTP", "mot de passe à usage unique"),))
        fondu = general.fusionner(precis)
        assert len(fondu.termes) == 1
        assert fondu.termes[0].sens == "mot de passe à usage unique"

    def test_la_casse_ne_cree_pas_de_doublon(self):
        fondu = Contexte(termes=(Terme("Casa"),)).fusionner(Contexte(termes=(Terme("CASA"),)))
        assert len(fondu.termes) == 1

    def test_les_deux_sources_se_completent(self):
        fondu = Contexte(termes=(Terme("CASA"),)).fusionner(Contexte(termes=(Terme("OTP"),)))
        assert {t.ecriture for t in fondu.termes} == {"CASA", "OTP"}

    def test_fusionner_ne_modifie_aucun_des_deux(self):
        general = Contexte(termes=(Terme("CASA"),))
        general.fusionner(Contexte(termes=(Terme("OTP"),)))
        assert len(general.termes) == 1
