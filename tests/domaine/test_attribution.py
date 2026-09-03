"""Une phrase à cheval sur deux locuteurs ne doit désigner personne."""

from __future__ import annotations

from greffier.domaine.attribution import PART_MINIMALE, temps_par_voix, voix_de
from greffier.domaine.modeles import Intervalle, TourDeParole


def tour(voix: str, debut: float, fin: float) -> TourDeParole:
    return TourDeParole(intervalle=Intervalle(debut, fin), voix=voix)


class TestVoixDe:
    def test_une_phrase_dans_un_seul_tour_va_a_cette_voix(self):
        tours = [tour("0", 0.0, 8.0), tour("1", 8.4, 17.0)]
        assert voix_de(Intervalle(0.0, 7.7), tours) == "0"

    def test_une_phrase_sans_aucun_tour_ne_designe_personne(self):
        assert voix_de(Intervalle(0.0, 5.0), []) is None
        assert voix_de(Intervalle(30.0, 35.0), [tour("0", 0.0, 8.0)]) is None

    def test_un_debord_de_quelques_centiemes_ne_change_rien(self):
        """Les bornes des deux découpes ne coïncident jamais exactement.

        Mesuré : la dernière réplique de la réunion de table tenait 0,98 — un
        chevauchement de 0,2 s sur le tour voisin. Refuser de trancher là
        laisserait la moitié des phrases sans voix.
        """
        tours = [tour("1", 41.9, 50.4), tour("0", 35.0, 41.2)]
        assert voix_de(Intervalle(41.0, 50.4), tours) == "1"

    def test_une_phrase_qui_enjambe_un_changement_de_locuteur_ne_designe_personne(self):
        """Le cas mesuré : « Merci Pierre… », dit par Jacques, donné à Pierre.

        La phrase transcrite couvre 9,6 s du tour de Pierre et 6,1 s de celui
        de Jacques, soit 0,61 pour le meneur. L'ancienne règle du plus bavard
        attribuait la phrase entière à Pierre.
        """
        tours = [tour("pierre", 24.55, 34.14), tour("jacques", 34.96, 41.07)]
        assert voix_de(Intervalle(23.77, 41.07), tours) is None

    def test_un_partage_moitie_moitie_ne_designe_personne(self):
        tours = [tour("0", 0.0, 5.0), tour("1", 5.0, 10.0)]
        assert voix_de(Intervalle(0.0, 10.0), tours) is None

    def test_le_seuil_est_franchi_a_la_part_minimale(self):
        """Pile au seuil, on tranche : le refus commence en dessous."""
        tours = [tour("0", 0.0, 8.0), tour("1", 8.0, 10.0)]
        assert voix_de(Intervalle(0.0, 10.0), tours, PART_MINIMALE) == "0"
        assert voix_de(Intervalle(0.0, 10.0), tours, 0.81) is None

    def test_les_morceaux_epars_d_une_meme_voix_se_cumulent(self):
        """Une voix coupée en deux par une interjection reste la même voix."""
        tours = [tour("0", 0.0, 4.0), tour("1", 4.0, 4.5), tour("0", 4.5, 10.0)]
        assert voix_de(Intervalle(0.0, 10.0), tours) == "0"


class TestTempsParVoix:
    def test_chaque_voix_recoit_son_temps_de_recouvrement(self):
        tours = [tour("0", 0.0, 4.0), tour("1", 4.0, 10.0)]
        assert temps_par_voix(Intervalle(2.0, 6.0), tours) == {"0": 2.0, "1": 2.0}

    def test_un_tour_hors_de_la_phrase_ne_compte_pas(self):
        assert temps_par_voix(Intervalle(0.0, 3.0), [tour("0", 5.0, 9.0)]) == {}
