"""Qui parle, d'après le canal.

Le cas nommé : sur une réunion réelle du 25 août 2026, la voix de la personne
qui enregistrait est arrivée 12 dB sous celle des autres. Moyennée avec elles,
elle se retrouvait 18 dB sous le mélange et la segmentation ne l'a jamais vue.
Treize minutes de parole absentes du compte rendu.
"""

from __future__ import annotations

from greffier.domaine.canaux import Reglages, retirer, soustraire, tours_locaux
from greffier.domaine.modeles import Intervalle

PAS = 0.025  # 25 ms, comme l'adaptateur


def niveaux(motif: list[tuple[float, float, int]]) -> tuple[list[float], list[float]]:
    """Construit deux suites de niveaux depuis (micro_db, systeme_db, trames)."""
    micro: list[float] = []
    systeme: list[float] = []
    for m, s, combien in motif:
        micro += [m] * combien
        systeme += [s] * combien
    return micro, systeme


class TestVoixFaibleMaisLocale:
    def test_une_voix_12_dB_sous_les_autres_est_quand_meme_vue(self) -> None:
        # Le cas du 25 août : le micro à -34 dB pendant que la boucle système
        # est à -22. Le moyennage la perdait ; le canal la retrouve.
        micro, systeme = niveaux([(-60, -22, 40), (-34, -50, 80), (-60, -22, 40)])
        tours = tours_locaux(micro, systeme, PAS)
        assert len(tours) == 1
        assert tours[0].duree == 80 * PAS

    def test_un_micro_plus_faible_que_la_boucle_n_est_pas_retenu(self) -> None:
        # Pendant que les autres parlent, le micro capte leur écho ou du bruit.
        micro, systeme = niveaux([(-34, -22, 200)])
        assert tours_locaux(micro, systeme, PAS) == []

    def test_la_marge_protege_de_la_reinjection(self) -> None:
        # Écoute par haut-parleurs : le micro réentend les enceintes, un peu
        # au-dessus de la boucle. Sans marge, tout passerait pour local.
        micro, systeme = niveaux([(-30, -33, 200)])
        assert tours_locaux(micro, systeme, PAS) == []
        # Avec une marge nulle, la même entrée est retenue : c'est bien la marge
        # qui décide, pas un autre effet.
        souple = Reglages(marge_db=0.0)
        assert tours_locaux(micro, systeme, PAS, souple) != []


class TestBruitDeFond:
    def test_le_silence_de_la_reunion_n_est_pas_de_la_parole(self) -> None:
        # Personne ne parle : la boucle est muette, et le bruit de la pièce
        # domine. Sans plancher, tous les silences deviendraient des tours.
        micro, systeme = niveaux([(-52, -75, 400)])
        assert tours_locaux(micro, systeme, PAS) == []

    def test_le_plancher_se_regle(self) -> None:
        micro, systeme = niveaux([(-52, -75, 400)])
        bas = Reglages(plancher_db=-60.0)
        assert tours_locaux(micro, systeme, PAS, bas) != []


class TestDecoupage:
    def test_les_silences_d_une_phrase_ne_coupent_pas_le_tour(self) -> None:
        # 0,5 s de silence au milieu d'une phrase : un seul tour, pas deux.
        micro, systeme = niveaux([
            (-30, -60, 40), (-60, -60, 20), (-30, -60, 40),
        ])
        tours = tours_locaux(micro, systeme, PAS)
        assert len(tours) == 1

    def test_un_vrai_silence_separe_deux_tours(self) -> None:
        # 1,5 s : la personne a fini, quelqu'un d'autre a parlé entre-temps.
        micro, systeme = niveaux([
            (-30, -60, 40), (-60, -60, 60), (-30, -60, 40),
        ])
        assert len(tours_locaux(micro, systeme, PAS)) == 2

    def test_un_oui_isole_est_ecarte(self) -> None:
        # 0,5 s : un acquiescement. Les garder ferait des centaines de tours.
        micro, systeme = niveaux([(-60, -60, 40), (-30, -60, 20), (-60, -60, 40)])
        assert tours_locaux(micro, systeme, PAS) == []

    def test_une_phrase_courte_est_gardee(self) -> None:
        micro, systeme = niveaux([(-60, -60, 40), (-30, -60, 40), (-60, -60, 40)])
        assert len(tours_locaux(micro, systeme, PAS)) == 1


class TestRobustesse:
    def test_des_suites_de_longueurs_differentes_ne_plantent_pas(self) -> None:
        micro = [-30.0] * 100
        systeme = [-60.0] * 40
        tours = tours_locaux(micro, systeme, PAS)
        assert tours and tours[0].fin <= 40 * PAS

    def test_une_entree_vide_ne_donne_aucun_tour(self) -> None:
        assert tours_locaux([], [], PAS) == []

    def test_un_pas_nul_est_refuse(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="pas"):
            tours_locaux([-30.0], [-60.0], 0.0)

    def test_une_parole_qui_court_jusqu_a_la_fin_est_close(self) -> None:
        micro, systeme = niveaux([(-60, -60, 40), (-30, -60, 60)])
        tours = tours_locaux(micro, systeme, PAS)
        assert len(tours) == 1
        assert tours[0].fin == 100 * PAS


class TestRetirerLesDoublons:
    def test_un_tour_distant_couvert_par_un_tour_local_disparait(self) -> None:
        # La segmentation ne voit que la boucle système, mais un participant qui
        # parle en même temps laisse un tour à cheval. Compter les deux ferait
        # deux personnes là où une tient la parole.
        distants = [Intervalle(10.0, 14.0)]
        locaux = [Intervalle(9.0, 15.0)]
        assert retirer(distants, locaux) == []

    def test_un_tour_distant_independant_est_conserve(self) -> None:
        distants = [Intervalle(30.0, 40.0)]
        locaux = [Intervalle(9.0, 15.0)]
        assert retirer(distants, locaux) == distants

    def test_un_simple_chevauchement_partiel_ne_supprime_rien(self) -> None:
        # Un quart recouvert : les deux ont parlé, on garde les deux.
        distants = [Intervalle(10.0, 20.0)]
        locaux = [Intervalle(18.0, 22.0)]
        assert retirer(distants, locaux) == distants

    def test_sans_tour_local_rien_ne_change(self) -> None:
        distants = [Intervalle(1.0, 2.0), Intervalle(3.0, 4.0)]
        assert retirer(distants, []) == distants


class TestQuiParle:
    """Ce que l'interface affiche pendant la réunion, sans consulter un modèle."""

    def test_le_silence(self) -> None:
        from greffier.domaine.canaux import QuiParle, qui_parle

        assert qui_parle(-70, -70) is QuiParle.PERSONNE

    def test_toi_seul(self) -> None:
        from greffier.domaine.canaux import QuiParle, qui_parle

        assert qui_parle(-30, -70) is QuiParle.TOI

    def test_les_autres_seuls(self) -> None:
        from greffier.domaine.canaux import QuiParle, qui_parle

        assert qui_parle(-70, -25) is QuiParle.LES_AUTRES

    def test_un_vrai_chevauchement(self) -> None:
        from greffier.domaine.canaux import QuiParle, qui_parle

        assert qui_parle(-20, -35) is QuiParle.LES_DEUX

    def test_le_micro_qui_reentend_les_enceintes_n_est_pas_toi(self) -> None:
        # Écoute par haut-parleurs : les deux canaux sont actifs, mais le micro
        # ne domine pas. Afficher « les deux » ferait clignoter l'interface à
        # chaque phrase des autres.
        from greffier.domaine.canaux import QuiParle, qui_parle

        assert qui_parle(-28, -25) is QuiParle.LES_AUTRES


class TestPresentielContreVisio:
    """La provenance identifie quelqu'un en visio, personne autour d'une table.

    Un portable posé au milieu d'une table n'a rien dans sa boucle système :
    tous les participants parlent dans le même micro. Appliquer quand même la
    séparation par canal en faisait **une seule voix**, celle de la personne qui
    enregistrait. Mesuré : trois locuteurs ramenés à une étiquette « moi ».
    """

    def test_en_visio_la_voix_locale_se_distingue(self) -> None:
        # Le micro domine la boucle : c'est la personne qui enregistre.
        micro, systeme = niveaux([(-30, -60, 60)])
        assert tours_locaux(micro, systeme, PAS)

    def test_une_boucle_muette_n_est_pas_une_preuve_de_parole_locale(self) -> None:
        # Autour d'une table, la boucle est à -240 dB en permanence : chaque
        # trame de parole « domine » donc la boucle, et tout deviendrait local.
        # C'est à l'adaptateur de ne pas appeler cette fonction dans ce cas,
        # mais le calcul lui-même doit rester lisible pour qui le relit.
        micro, systeme = niveaux([(-25, -240, 80)])
        tours = tours_locaux(micro, systeme, PAS)
        assert tours, "le calcul reste juste : c'est son usage qui doit être conditionné"


class TestVisioOuTable:
    """Reconnaître une visio d'une réunion tenue autour d'une table.

    Premier essai raté, et il a coûté un compte rendu : tester si la boucle
    système est non nulle. Sur une réunion de table réelle elle relevait -53 dB,
    du son y ayant fui, et conclure « visio » attribuait les trente minutes à la
    personne qui enregistrait.

    Ce qui tranche est relatif : en visio les autres dominent le micro une bonne
    part du temps, puisqu'ils passent par les haut-parleurs. Mesuré, 57,7 % des
    trames sur une visio d'une heure, 0,0 % sur une réunion de table.
    """

    def test_une_visio_est_reconnue(self) -> None:
        from greffier.domaine.canaux import en_visio

        # Les autres parlent la moitié du temps.
        micro, systeme = niveaux([(-50, -30, 100), (-30, -60, 100)])
        assert en_visio(micro, systeme)

    def test_une_reunion_de_table_n_est_pas_prise_pour_une_visio(self) -> None:
        from greffier.domaine.canaux import en_visio

        # Tout le monde passe par le micro, la boucle ne porte rien.
        micro, systeme = niveaux([(-35, -240, 200)])
        assert not en_visio(micro, systeme)

    def test_une_boucle_qui_bruite_sans_porter_de_parole_reste_du_presentiel(
        self,
    ) -> None:
        # Le cas qui a échoué : une boucle à -53 dB, jamais dominante.
        from greffier.domaine.canaux import en_visio

        micro, systeme = niveaux([(-35, -53, 200)])
        assert not en_visio(micro, systeme)

    def test_une_seule_intervention_distante_ne_fait_pas_une_visio(self) -> None:
        # Une notification, un son joué en séance : deux trames sur deux cents.
        from greffier.domaine.canaux import en_visio

        micro, systeme = niveaux([(-35, -240, 198), (-50, -30, 2)])
        assert not en_visio(micro, systeme)

    def test_une_entree_vide_ne_conclut_pas_a_la_visio(self) -> None:
        from greffier.domaine.canaux import en_visio

        assert not en_visio([], [])


class TestSoustraire:
    """Ôter d'un passage ce que le canal attribue à la personne au micro.

    Le cas mesuré : la transcription coupe à la phrase, pas au changement de
    locuteur. Un extrait de 1,5 s portant 0,6 s de voix locale donnait une
    empreinte mêlée, et la même personne devenait deux participants.
    """

    def test_une_portion_au_milieu_coupe_en_deux(self) -> None:
        restes = soustraire(Intervalle(0, 10), [Intervalle(4, 6)])
        assert restes == [Intervalle(0, 4), Intervalle(6, 10)]

    def test_une_portion_en_tete_raccourcit_le_debut(self) -> None:
        assert soustraire(Intervalle(13.2, 14.7), [Intervalle(9.5, 13.8)]) == [
            Intervalle(13.8, 14.7)
        ]

    def test_un_passage_entierement_couvert_ne_laisse_rien(self) -> None:
        assert soustraire(Intervalle(2, 4), [Intervalle(0, 10)]) == []

    def test_un_passage_disjoint_reste_entier(self) -> None:
        assert soustraire(Intervalle(0, 3), [Intervalle(5, 8)]) == [Intervalle(0, 3)]

    def test_plusieurs_portions_se_soustraient_l_une_apres_l_autre(self) -> None:
        restes = soustraire(Intervalle(0, 12), [Intervalle(2, 4), Intervalle(7, 9)])
        assert restes == [Intervalle(0, 2), Intervalle(4, 7), Intervalle(9, 12)]

    def test_sans_rien_a_oter_l_intervalle_ne_change_pas(self) -> None:
        assert soustraire(Intervalle(0, 5), []) == [Intervalle(0, 5)]
