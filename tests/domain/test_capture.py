"""La capture avance-t-elle ? La seule question qui compte pendant la réunion."""

from greffier.domain.capture import TOURS_AVANT_ALERTE, SurveillanceDeCapture


class TestQuandLaCaptureAvance:
    def test_un_fichier_qui_grossit_ne_dit_rien(self):
        monitoring = SurveillanceDeCapture()
        assert monitoring.observe(1000) == ""
        assert monitoring.observe(2000) == ""
        assert monitoring.observe(3000) == ""

    def test_le_premier_constat_ne_conclut_rien(self):
        """Sans point de comparaison, on ne sait rien : se taire est juste."""
        assert SurveillanceDeCapture().observe(0) == ""


class TestQuandLaCaptureSArrete:
    """Avant, une capture morte ne se voyait qu'au traitement, réunion finie.

    Le 2026-09-09, une réunion n'a rien enregistré du tout et rien ne l'a dit :
    aucun fichier, aucune alerte, la perte n'a été découverte qu'en cherchant
    pourquoi le compte rendu n'arrivait pas.
    """

    def test_l_immobilite_finit_par_alerter(self):
        monitoring = SurveillanceDeCapture()
        monitoring.observe(5000)
        raisons = [monitoring.observe(5000) for _ in range(TOURS_AVANT_ALERTE)]
        assert raisons[-1], "l'alerte doit finir par sortir"
        assert "n'avance plus" in raisons[-1]

    def test_elle_ne_crie_pas_au_premier_tour_immobile(self):
        """Un tampon d'écriture qui se vide n'est pas une panne."""
        monitoring = SurveillanceDeCapture()
        monitoring.observe(5000)
        assert monitoring.observe(5000) == ""

    def test_elle_ne_le_dit_qu_une_fois(self):
        monitoring = SurveillanceDeCapture()
        monitoring.observe(5000)
        dites = [r for _ in range(10) if (r := monitoring.observe(5000))]
        assert len(dites) == 1, "répéter à chaque tour noierait le message"

    def test_une_reprise_rearme_la_surveillance(self):
        """Un changement de matériel peut interrompre la capture le temps d'un morceau."""
        monitoring = SurveillanceDeCapture()
        monitoring.observe(5000)
        for _ in range(TOURS_AVANT_ALERTE):
            monitoring.observe(5000)
        assert monitoring.observe(9000) == "", "ça repart : plus rien à dire"
        for _ in range(TOURS_AVANT_ALERTE):
            dernier = monitoring.observe(9000)
        assert dernier, "une seconde panne doit se dire aussi"

    def test_un_fichier_qui_retrecit_compte_comme_immobile(self):
        """Ça n'arrive pas normalement, et ne doit donc pas passer inaperçu."""
        monitoring = SurveillanceDeCapture()
        monitoring.observe(9000)
        raisons = [monitoring.observe(1000) for _ in range(TOURS_AVANT_ALERTE)]
        assert raisons[-1]
