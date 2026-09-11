"""La capture avance-t-elle ? La seule question qui compte pendant la réunion."""

from greffier.domain.capture import TURNS_BEFORE_ALERT, CaptureWatch


class TestWhileTheCaptureAdvances:
    def test_a_file_that_grows_says_nothing(self):
        monitoring = CaptureWatch()
        assert monitoring.observe(1000) == ""
        assert monitoring.observe(2000) == ""
        assert monitoring.observe(3000) == ""

    def test_the_first_reading_concludes_nothing(self):
        """Sans point de comparaison, on ne sait rien : se taire est juste."""
        assert CaptureWatch().observe(0) == ""


class TestWhenTheCaptureStops:
    """Avant, une capture morte ne se voyait qu'au traitement, réunion finie.

    Le 2026-09-09, une réunion n'a rien enregistré du tout et rien ne l'a dit :
    aucun fichier, aucune alerte, la perte n'a été découverte qu'en cherchant
    pourquoi le compte rendu n'arrivait pas.
    """

    def test_stillness_ends_up_raising_the_alarm(self):
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        raisons = [monitoring.observe(5000) for _ in range(TURNS_BEFORE_ALERT)]
        assert raisons[-1], "l'alerte doit finir par sortir"
        assert "n'avance plus" in raisons[-1]

    def test_it_does_not_cry_out_on_the_first_still_turn(self):
        """Un tampon d'écriture qui se vide n'est pas une panne."""
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        assert monitoring.observe(5000) == ""

    def test_it_says_so_only_once(self):
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        dites = [r for _ in range(10) if (r := monitoring.observe(5000))]
        assert len(dites) == 1, "répéter à chaque tour noierait le message"

    def test_starting_again_rearms_the_watch(self):
        """Un changement de matériel peut interrompre la capture le temps d'un morceau."""
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        for _ in range(TURNS_BEFORE_ALERT):
            monitoring.observe(5000)
        assert monitoring.observe(9000) == "", "ça repart : plus rien à dire"
        for _ in range(TURNS_BEFORE_ALERT):
            dernier = monitoring.observe(9000)
        assert dernier, "une seconde panne doit se dire aussi"

    def test_a_file_that_shrinks_counts_as_still(self):
        """Ça n'arrive pas normalement, et ne doit donc pas passer inaperçu."""
        monitoring = CaptureWatch()
        monitoring.observe(9000)
        raisons = [monitoring.observe(1000) for _ in range(TURNS_BEFORE_ALERT)]
        assert raisons[-1]
