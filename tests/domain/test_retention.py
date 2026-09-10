"""Ce qu'on garde, et pendant combien de temps."""

import pytest

from greffier.domain.retention import Gesture, Rule


class TestReglesImpossibles:
    def test_un_delai_negatif_est_refuse(self):
        with pytest.raises(ValueError, match="négatif"):
            Rule(compresser_apres=-1)

    def test_effacer_avant_de_compresser_est_refuse(self):
        """Le second geste englobe le premier : l'ordre inverse se contredit."""
        with pytest.raises(ValueError, match="doit venir après"):
            Rule(compresser_apres=30, effacer_apres=7)


class TestCompression:
    def test_avant_le_delai_on_ne_touche_a_rien(self):
        assert Rule(compresser_apres=7).decide(3, True, False) is Gesture.RIEN

    def test_apres_le_delai_on_compresse(self):
        assert Rule(compresser_apres=7).decide(8, True, False) is Gesture.COMPRESSER

    def test_un_audio_deja_compresse_est_laisse(self):
        assert Rule(compresser_apres=7).decide(30, True, True) is Gesture.RIEN

    def test_un_delai_nul_desactive_la_compression(self):
        assert Rule(compresser_apres=0).decide(999, True, False) is Gesture.RIEN


class TestEffacement:
    def test_desactive_par_defaut(self):
        """Effacer perd la seule pièce qu'on ne peut pas refaire."""
        assert Rule().effacer_apres == 0
        assert Rule().decide(9999, True, True) is Gesture.RIEN

    def test_active_il_efface_au_dela_du_delai(self):
        regle = Rule(compresser_apres=7, effacer_apres=90)
        assert regle.decide(91, True, True) is Gesture.EFFACER

    def test_il_l_emporte_sur_la_compression(self):
        regle = Rule(compresser_apres=7, effacer_apres=90)
        assert regle.decide(120, True, False) is Gesture.EFFACER


class TestUneReunionNonTranscriteEstIntouchable:
    """Son audio est tout ce qui existe d'elle."""

    def test_jamais_compressee(self):
        assert Rule(compresser_apres=1).decide(365, False, False) is Gesture.RIEN

    def test_jamais_effacee(self):
        regle = Rule(compresser_apres=7, effacer_apres=30)
        assert regle.decide(365, False, True) is Gesture.RIEN
