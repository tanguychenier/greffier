"""La capture avance-t-elle ? La seule question qui compte pendant la réunion."""

from greffier.domaine.capture import TOURS_AVANT_ALERTE, SurveillanceDeCapture


class TestQuandLaCaptureAvance:
    def test_un_fichier_qui_grossit_ne_dit_rien(self):
        surveillance = SurveillanceDeCapture()
        assert surveillance.constater(1000) == ""
        assert surveillance.constater(2000) == ""
        assert surveillance.constater(3000) == ""

    def test_le_premier_constat_ne_conclut_rien(self):
        """Sans point de comparaison, on ne sait rien : se taire est juste."""
        assert SurveillanceDeCapture().constater(0) == ""


class TestQuandLaCaptureSArrete:
    """Avant, une capture morte ne se voyait qu'au traitement, réunion finie.

    Le 2026-09-09, une réunion n'a rien enregistré du tout et rien ne l'a dit :
    aucun fichier, aucune alerte, la perte n'a été découverte qu'en cherchant
    pourquoi le compte rendu n'arrivait pas.
    """

    def test_l_immobilite_finit_par_alerter(self):
        surveillance = SurveillanceDeCapture()
        surveillance.constater(5000)
        raisons = [surveillance.constater(5000) for _ in range(TOURS_AVANT_ALERTE)]
        assert raisons[-1], "l'alerte doit finir par sortir"
        assert "n'avance plus" in raisons[-1]

    def test_elle_ne_crie_pas_au_premier_tour_immobile(self):
        """Un tampon d'écriture qui se vide n'est pas une panne."""
        surveillance = SurveillanceDeCapture()
        surveillance.constater(5000)
        assert surveillance.constater(5000) == ""

    def test_elle_ne_le_dit_qu_une_fois(self):
        surveillance = SurveillanceDeCapture()
        surveillance.constater(5000)
        dites = [r for _ in range(10) if (r := surveillance.constater(5000))]
        assert len(dites) == 1, "répéter à chaque tour noierait le message"

    def test_une_reprise_rearme_la_surveillance(self):
        """Un changement de matériel peut interrompre la capture le temps d'un morceau."""
        surveillance = SurveillanceDeCapture()
        surveillance.constater(5000)
        for _ in range(TOURS_AVANT_ALERTE):
            surveillance.constater(5000)
        assert surveillance.constater(9000) == "", "ça repart : plus rien à dire"
        for _ in range(TOURS_AVANT_ALERTE):
            dernier = surveillance.constater(9000)
        assert dernier, "une seconde panne doit se dire aussi"

    def test_un_fichier_qui_retrecit_compte_comme_immobile(self):
        """Ça n'arrive pas normalement, et ne doit donc pas passer inaperçu."""
        surveillance = SurveillanceDeCapture()
        surveillance.constater(9000)
        raisons = [surveillance.constater(1000) for _ in range(TOURS_AVANT_ALERTE)]
        assert raisons[-1]
