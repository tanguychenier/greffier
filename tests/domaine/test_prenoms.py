"""Ce qui peut entrer en banque sous le nom d'une personne."""

import pytest

from greffier.domaine.prenoms import normaliser, refus, valable


class TestCeQuiPasse:
    @pytest.mark.parametrize("nom", [
        "Marcel", "Tanguy", "Anne-Sophie", "Jean Marcel", "Li", "Ólafur",
        "Nguyễn", "O'Connor", "Zoé",
    ])
    def test_un_prenom_est_accepte(self, nom):
        assert valable(nom), refus(nom)


class TestCeQuiNePassePas:
    def test_le_libelle_de_l_interface_est_refuse(self):
        """Le cas mesuré : la banque du poste portait « A nommer ».

        C'est ce que la colonne « Nom » affiche pour une voix qui n'en a pas
        encore. Entrée en banque, elle est reconnue à chaque réunion suivante.
        """
        assert not valable("A nommer")
        assert not valable("à nommer")
        assert "pas un prénom" in refus("A nommer")

    @pytest.mark.parametrize("nom", [
        "", "   ", "M", "?", "-", "Les autres", "inconnu", "Personne",
        "Voix 12", "Personne 3", "42", "...", "Sans nom",
    ])
    def test_ce_qui_n_est_pas_un_prenom_est_refuse(self, nom):
        assert not valable(nom)

    def test_une_phrase_entiere_est_refusee(self):
        assert not valable("je crois que c'était plutôt Marcel qui parlait là")

    def test_le_refus_dit_pourquoi(self):
        """Un refus sans raison fait recommencer la même saisie."""
        assert refus("") and refus("M") and refus("Voix 12")


class TestNormalisation:
    def test_la_casse_est_unifiee(self):
        """Sans quoi « marcel » et « Marcel » sont deux personnes en banque,
        chacune avec la moitié des empreintes."""
        assert normaliser("marcel") == "Marcel"

    def test_les_espaces_se_reduisent(self):
        assert normaliser("  Anne   Sophie ") == "Anne Sophie"

    def test_un_nom_deja_propre_ne_bouge_pas(self):
        assert normaliser("Anne-Sophie") == "Anne-Sophie"

    def test_la_suite_du_nom_garde_sa_casse(self):
        assert normaliser("McCarthy") == "McCarthy"
