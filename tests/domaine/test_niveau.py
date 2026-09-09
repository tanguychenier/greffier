"""Juger un niveau de parole, pas un niveau de silence."""

from greffier.domaine.niveau import (
    BON_DB,
    INSUFFISANT_DB,
    MUET_DB,
    Verdict,
    dire,
    juger,
    suffisant,
)


class TestSeuils:
    def test_le_seuil_d_invention_est_celui_qui_a_ete_mesure(self):
        """À -43 dB, « Test, test de réunion » est devenu « Merci d'avoir
        regardé cette vidéo ! »."""
        assert INSUFFISANT_DB == -43.0

    def test_le_seuil_muet_est_celui_de_la_chaine(self):
        """Deux seuils pour la même question finiraient par se contredire."""
        from greffier.application.traiter import SEUIL_MUET_DB

        assert MUET_DB == SEUIL_MUET_DB

    def test_les_seuils_sont_ordonnes(self):
        assert MUET_DB < INSUFFISANT_DB < BON_DB < 0


class TestJugement:
    def test_une_parole_franche_est_bonne(self):
        assert juger(-22.0) is Verdict.BON

    def test_juste_sous_le_bon_c_est_faible(self):
        assert juger(-35.0) is Verdict.FAIBLE

    def test_sous_le_seuil_d_invention_c_est_insuffisant(self):
        assert juger(-50.0) is Verdict.INSUFFISANT

    def test_le_vrai_silence_est_muet(self):
        assert juger(-90.0) is Verdict.MUET

    def test_les_bornes_appartiennent_au_meilleur_verdict(self):
        assert juger(BON_DB) is Verdict.BON
        assert juger(INSUFFISANT_DB) is Verdict.FAIBLE


class TestCeQueLOnDit:
    """Un niveau sans quoi-faire ne sert à personne."""

    def test_muet_dit_ou_chercher(self):
        phrase = dire(-90.0)
        assert "sourdine" in phrase
        assert "autorisation micro" in phrase

    def test_insuffisant_dit_que_le_modele_invente(self):
        """C'est le fait contre-intuitif : moins de signal, pas moins de texte."""
        assert "invente" in dire(-50.0)

    def test_faible_dit_le_gain_d_un_casque(self):
        assert "casque" in dire(-35.0)

    def test_bon_reste_bref(self):
        assert dire(-20.0) == "Bon niveau (-20 dB)."

    def test_chaque_phrase_porte_le_chiffre(self):
        for db in (-90.0, -50.0, -35.0, -20.0):
            assert f"{db:.0f} dB" in dire(db)


class TestDemarrage:
    def test_on_peut_demarrer_en_faible(self):
        """Une réunion qui a lieu vaut mieux qu'une réunion refusée."""
        assert suffisant(-35.0) is True

    def test_on_avertit_sous_le_seuil_d_invention(self):
        assert suffisant(-50.0) is False
        assert suffisant(-90.0) is False


class TestSurveillancePendantLaReunion:
    """Le fichier grossit mais ne contient presque rien.

    Distinct d'une capture qui n'avance plus : ici le son arrive, trop faible.
    Le dire pendant la réunion laisse une chance de rapprocher le micro ; le
    découvrir au compte rendu n'en laisse aucune.
    """

    def surveillance(self):
        from greffier.domaine.niveau import SurveillanceDeNiveau

        return SurveillanceDeNiveau()

    def test_elle_ne_conclut_pas_tout_de_suite(self):
        """Personne ne parle en continu : conclure au premier relevé
        reviendrait à alerter parce que quelqu'un écoutait."""
        surveillance = self.surveillance()
        assert surveillance.constater(-60.0) == ""

    def test_un_niveau_durablement_faible_finit_par_alerter(self):
        from greffier.domaine.niveau import RELEVES_AVANT_ALERTE

        surveillance = self.surveillance()
        raisons = [surveillance.constater(-55.0) for _ in range(RELEVES_AVANT_ALERTE)]
        assert raisons[-1]
        assert "trop faible" in raisons[-1]

    def test_une_seule_phrase_forte_suffit_a_rassurer(self):
        """Le maximum et non la moyenne : entre deux phrases il y a du silence,
        et une moyenne mesure surtout les silences."""
        from greffier.domaine.niveau import RELEVES_AVANT_ALERTE

        surveillance = self.surveillance()
        surveillance.constater(-22.0)
        raisons = [surveillance.constater(-80.0) for _ in range(RELEVES_AVANT_ALERTE)]
        assert not any(raisons)

    def test_elle_ne_le_dit_qu_une_fois(self):
        """Le niveau ne se corrige pas sans interrompre : répéter n'ajoute rien."""
        from greffier.domaine.niveau import RELEVES_AVANT_ALERTE

        surveillance = self.surveillance()
        dites = [
            raison
            for _ in range(RELEVES_AVANT_ALERTE * 3)
            if (raison := surveillance.constater(-55.0))
        ]
        assert len(dites) == 1

    def test_l_alerte_dit_le_niveau_et_quoi_faire(self):
        from greffier.domaine.niveau import RELEVES_AVANT_ALERTE

        surveillance = self.surveillance()
        for _ in range(RELEVES_AVANT_ALERTE):
            raison = surveillance.constater(-55.0)
        assert "-55 dB" in raison
        assert "invente" in raison
