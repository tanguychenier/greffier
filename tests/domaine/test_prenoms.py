"""Ce qui peut entrer en banque sous le nom d'une personne."""

import pytest

from greffier.domain.first_names import acceptable, normalise, refusal


class TestCeQuiPasse:
    @pytest.mark.parametrize("name", [
        "Michel", "Tanguy", "Anne-Sophie", "Jean Michel", "Li", "Ólafur",
        "Nguyễn", "O'Connor", "Zoé",
    ])
    def test_un_prenom_est_accepte(self, name):
        assert acceptable(name), refusal(name)


class TestCeQuiNePassePas:
    def test_le_libelle_de_l_interface_est_refuse(self):
        """Le cas mesuré : la banque du poste portait « A nommer ».

        C'est ce que la colonne « Nom » affiche pour une voix qui n'en a pas
        encore. Entrée en banque, elle est reconnue à chaque réunion suivante.
        """
        assert not acceptable("A nommer")
        assert not acceptable("à nommer")
        assert "pas un prénom" in refusal("A nommer")

    @pytest.mark.parametrize("name", [
        "", "   ", "M", "?", "-", "Les autres", "inconnu", "Personne",
        "Voix 12", "Personne 3", "42", "...", "Sans nom",
    ])
    def test_ce_qui_n_est_pas_un_prenom_est_refuse(self, name):
        assert not acceptable(name)

    def test_une_phrase_entiere_est_refusee(self):
        assert not acceptable("je crois que c'était plutôt Michel qui parlait là")

    def test_le_refus_dit_pourquoi(self):
        """Un refus sans raison fait recommencer la même saisie."""
        assert refusal("") and refusal("M") and refusal("Voix 12")


class TestNormalisation:
    def test_la_casse_est_unifiee(self):
        """Sans quoi « michel » et « Michel » sont deux personnes en banque,
        chacune avec la moitié des empreintes."""
        assert normalise("michel") == "Michel"

    def test_les_espaces_se_reduisent(self):
        assert normalise("  Anne   Sophie ") == "Anne Sophie"

    def test_un_nom_deja_propre_ne_bouge_pas(self):
        assert normalise("Anne-Sophie") == "Anne-Sophie"

    def test_la_suite_du_nom_garde_sa_casse(self):
        assert normalise("McCarthy") == "McCarthy"
