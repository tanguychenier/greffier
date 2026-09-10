"""Le contexte du milieu : ce qu'un modèle ne peut pas deviner."""

import pytest

from greffier.domain.context import (
    AMORCE_MAXIMUM,
    Context,
    Speaker_,
    Term,
)


class TestTerme:
    def test_un_sigle_porte_son_sens_pour_le_redacteur(self):
        assert Term("OTP", "mot de passe à usage unique").gloss == (
            "OTP (mot de passe à usage unique)"
        )

    def test_sans_sens_le_terme_reste_nu(self):
        assert Term("CASA").gloss == "CASA"

    def test_un_terme_sans_ecriture_est_refuse(self):
        with pytest.raises(ValueError, match="sans écriture"):
            Term("   ")


class TestAmorce:
    """Ce qui décide de l'orthographe pendant la transcription.

    Mesuré le 2026-09-09 sur une réunion réelle : « déploiement » rendu
    « exploitement », « emploi du temps » rendu « emploi fictif ». Ces mots ne
    sont nulle part dans ce qu'un modèle a appris.
    """

    def test_les_termes_et_les_noms_y_figurent_ensemble(self):
        context = Context(
            termes=(Term("CASA"),),
            intervenants=(Speaker_("Kerann"),),
        )
        prompt_seed = context.prompt_seed()
        assert "CASA" in prompt_seed
        assert "Kerann" in prompt_seed

    def test_le_sens_n_encombre_pas_l_amorce(self):
        """Le transcripteur ne raisonne pas : lui donner des définitions le noie."""
        prompt_seed = Context(termes=(Term("OTP", "mot de passe à usage unique"),)).prompt_seed()
        assert "OTP" in prompt_seed
        assert "usage unique" not in prompt_seed

    def test_un_contexte_vide_ne_produit_aucune_amorce(self):
        assert Context().prompt_seed() == ""

    def test_l_amorce_tient_dans_la_limite_du_modele(self):
        """whisper tronque au-delà de 224 jetons, sans prévenir."""
        context = Context(termes=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        assert len(context.prompt_seed()) <= AMORCE_MAXIMUM

    def test_ce_qui_ne_tient_pas_est_dit(self):
        context = Context(termes=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        assert context.ecartes(), "il faut pouvoir avertir plutôt que tronquer en silence"

    def test_aucun_terme_n_est_coupe_en_deux(self):
        """Une écriture coupée apprend une orthographe fausse : pire que rien."""
        context = Context(termes=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        for mot in context.prompt_seed().split("Vocabulaire : ")[1].rstrip(".").split(", "):
            assert mot.startswith("terme-") and len(mot) == len("terme-000")

    def test_un_terme_repete_ne_compte_qu_une_fois(self):
        prompt_seed = Context(termes=(Term("OTP"), Term("OTP"))).prompt_seed()
        assert prompt_seed.count("OTP") == 1


class TestEntete:
    """Ce que le rédacteur reçoit : les écritures **et** leur sens."""

    def test_les_sens_sont_donnes_au_redacteur(self):
        header = Context(termes=(Term("OTP", "mot de passe à usage unique"),)).header()
        assert "mot de passe à usage unique" in header

    def test_le_redacteur_est_prie_de_ne_pas_reciter_le_glossaire(self):
        header = Context(termes=(Term("OTP"),)).header()
        assert "que ceux dont il est question" in header

    def test_un_role_n_autorise_pas_a_preter_une_position(self):
        header = Context(intervenants=(Speaker_("Sophie", "cheffe de projet"),)).header()
        assert "jamais d'après son rôle" in header

    def test_un_contexte_vide_ne_dit_rien(self):
        assert Context().header() == ""


class TestFusion:
    """Le contexte du poste, complété par celui d'une réunion précise."""

    def test_le_plus_precis_l_emporte(self):
        general = Context(termes=(Term("OTP", "ancien sens"),))
        precis = Context(termes=(Term("OTP", "mot de passe à usage unique"),))
        fondu = general.join(precis)
        assert len(fondu.termes) == 1
        assert fondu.termes[0].sens == "mot de passe à usage unique"

    def test_la_casse_ne_cree_pas_de_doublon(self):
        fondu = Context(termes=(Term("Casa"),)).join(Context(termes=(Term("CASA"),)))
        assert len(fondu.termes) == 1

    def test_les_deux_sources_se_completent(self):
        fondu = Context(termes=(Term("CASA"),)).join(Context(termes=(Term("OTP"),)))
        assert {t.ecriture for t in fondu.termes} == {"CASA", "OTP"}

    def test_fusionner_ne_modifie_aucun_des_deux(self):
        general = Context(termes=(Term("CASA"),))
        general.join(Context(termes=(Term("OTP"),)))
        assert len(general.termes) == 1
