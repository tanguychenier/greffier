"""Savoir si une version est postérieure à une autre."""

from greffier.domaine.version import lire, plus_recente


class TestLecture:
    def test_trois_nombres(self):
        assert lire("1.2.3") == (1, 2, 3)

    def test_le_v_des_etiquettes_est_accepte(self):
        assert lire("v0.2.0") == (0, 2, 0)

    def test_deux_nombres_suffisent(self):
        assert lire("0.2") == (0, 2, 0)

    def test_un_suffixe_est_ignore(self):
        assert lire("1.2.3-essai") == (1, 2, 3)

    def test_ce_qui_n_est_pas_une_version_est_refuse(self):
        assert lire("dernière") is None
        assert lire("") is None


class TestComparaison:
    def test_une_version_superieure_est_detectee(self):
        assert plus_recente("0.3.0", "0.2.0") is True

    def test_la_meme_version_ne_propose_rien(self):
        assert plus_recente("0.2.0", "0.2.0") is False

    def test_une_version_anterieure_ne_propose_rien(self):
        assert plus_recente("0.1.0", "0.2.0") is False

    def test_dix_vient_apres_neuf(self):
        """Une comparaison de chaînes affirme exactement l'inverse.

        L'erreur ne se voit qu'au dixième incrément, soit des mois après la
        mise en service.
        """
        assert plus_recente("0.10.0", "0.9.0") is True
        assert plus_recente("0.9.0", "0.10.0") is False

    def test_le_correctif_compte(self):
        assert plus_recente("0.2.1", "0.2.0") is True

    def test_une_version_illisible_ne_propose_rien(self):
        assert plus_recente("dernière", "0.2.0") is False
        assert plus_recente("0.3.0", "inconnue") is False
