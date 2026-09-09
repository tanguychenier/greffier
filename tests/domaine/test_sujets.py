"""Reconnaître de quel sujet on parle — la difficulté réelle."""

import pytest

from greffier.domaine.sujets import MENTIONS_MINIMALES, Registre, Sujet


class TestUnSujetEtSesAppellations:
    def test_un_sujet_sans_nom_est_refuse(self):
        with pytest.raises(ValueError, match="sans nom"):
            Sujet("  ")

    def test_il_se_reconnait_sous_son_nom(self):
        assert Sujet("Oasis").reconnait("oasis") is True

    def test_il_se_reconnait_sous_ses_alias(self):
        """Personne ne peut deviner qu'« esup-oasis » désigne « Oasis »."""
        sujet = Sujet("Oasis", ("esup-oasis",))
        assert sujet.reconnait("esup oasis") is True

    def test_il_ne_se_reconnait_pas_ailleurs(self):
        assert Sujet("Oasis").reconnait("Copernic") is False


class TestComptage:
    def test_toutes_les_appellations_comptent_ensemble(self):
        """C'est tout l'intérêt du registre."""
        registre = Registre([Sujet("Oasis", ("esup-oasis",))])
        comptes = registre.compter("On parle d'Oasis, puis d'esup-oasis, puis d'Oasis.")
        assert comptes == {"Oasis": 3}

    def test_le_comptage_ignore_la_casse_et_les_accents(self):
        registre = Registre([Sujet("recette")])
        assert registre.compter("La Recette, la recette, la RECETTE") == {"recette": 3}

    def test_un_sujet_absent_n_apparait_pas(self):
        assert Registre([Sujet("Oasis")]).compter("On parle d'autre chose.") == {}

    def test_un_mot_plus_long_ne_compte_pas(self):
        """« prod » ne doit pas se compter dans « production »."""
        assert Registre([Sujet("prod")]).compter("la production tourne") == {}

    def test_un_alias_qui_contient_le_nom_ne_compte_pas_double(self):
        """« esup-oasis » contient « oasis » : c'est une mention, pas deux.

        Additionner les occurrences de chaque appellation faisait de trois
        mentions d'Oasis quatre.
        """
        registre = Registre([Sujet("Oasis", ("esup-oasis",))])
        assert registre.compter("Oasis, puis esup-oasis, puis Oasis") == {"Oasis": 3}

    def test_l_appellation_la_plus_longue_gagne(self):
        registre = Registre([Sujet("Oasis", ("esup-oasis",))])
        assert registre.compter("On parle d'esup-oasis") == {"Oasis": 1}


class TestSujetsRetenus:
    def test_les_sujets_traites_sortent_du_plus_present_au_moins(self):
        registre = Registre([Sujet("Oasis"), Sujet("recette")])
        texte = "Oasis " * 10 + "recette " * 4
        assert registre.sujets_de(texte) == ["Oasis", "recette"]

    def test_une_allusion_n_est_pas_un_sujet(self):
        """Ouvrir une carte pour chaque allusion la remplirait de bruit."""
        registre = Registre([Sujet("Docker")])
        assert registre.sujets_de("On a parlé de Docker une fois.") == []

    def test_le_seuil_reste_bas_mais_non_nul(self):
        assert 1 < MENTIONS_MINIMALES <= 5

    def test_le_seuil_est_reglable(self):
        registre = Registre([Sujet("Docker")])
        assert registre.sujets_de("Docker une fois.", minimum=1) == ["Docker"]


class TestRetrouverUnSujet:
    def test_par_son_nom(self):
        registre = Registre([Sujet("Oasis", carte="uXjV1=")])
        trouve = registre.par_nom("Oasis")
        assert trouve is not None and trouve.carte == "uXjV1="

    def test_par_un_alias(self):
        registre = Registre([Sujet("Oasis", ("esup-oasis",), carte="uXjV1=")])
        trouve = registre.par_nom("esup-oasis")
        assert trouve is not None and trouve.carte == "uXjV1="

    def test_un_sujet_inconnu_rend_rien(self):
        assert Registre([Sujet("Oasis")]).par_nom("Copernic") is None
