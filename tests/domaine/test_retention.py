"""Ce qu'on garde, et pendant combien de temps."""

import pytest

from greffier.domain.retention import Geste, Regle


class TestReglesImpossibles:
    def test_un_delai_negatif_est_refuse(self):
        with pytest.raises(ValueError, match="négatif"):
            Regle(compresser_apres=-1)

    def test_effacer_avant_de_compresser_est_refuse(self):
        """Le second geste englobe le premier : l'ordre inverse se contredit."""
        with pytest.raises(ValueError, match="doit venir après"):
            Regle(compresser_apres=30, effacer_apres=7)


class TestCompression:
    def test_avant_le_delai_on_ne_touche_a_rien(self):
        assert Regle(compresser_apres=7).decide(3, True, False) is Geste.RIEN

    def test_apres_le_delai_on_compresse(self):
        assert Regle(compresser_apres=7).decide(8, True, False) is Geste.COMPRESSER

    def test_un_audio_deja_compresse_est_laisse(self):
        assert Regle(compresser_apres=7).decide(30, True, True) is Geste.RIEN

    def test_un_delai_nul_desactive_la_compression(self):
        assert Regle(compresser_apres=0).decide(999, True, False) is Geste.RIEN


class TestEffacement:
    def test_desactive_par_defaut(self):
        """Effacer perd la seule pièce qu'on ne peut pas refaire."""
        assert Regle().effacer_apres == 0
        assert Regle().decide(9999, True, True) is Geste.RIEN

    def test_active_il_efface_au_dela_du_delai(self):
        regle = Regle(compresser_apres=7, effacer_apres=90)
        assert regle.decide(91, True, True) is Geste.EFFACER

    def test_il_l_emporte_sur_la_compression(self):
        regle = Regle(compresser_apres=7, effacer_apres=90)
        assert regle.decide(120, True, False) is Geste.EFFACER


class TestUneReunionNonTranscriteEstIntouchable:
    """Son audio est tout ce qui existe d'elle."""

    def test_jamais_compressee(self):
        assert Regle(compresser_apres=1).decide(365, False, False) is Geste.RIEN

    def test_jamais_effacee(self):
        regle = Regle(compresser_apres=7, effacer_apres=30)
        assert regle.decide(365, False, True) is Geste.RIEN
