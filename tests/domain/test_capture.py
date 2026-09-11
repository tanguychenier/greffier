"""Is the capture advancing? The only question that matters during a meeting."""

from greffier.domain.capture import TURNS_BEFORE_ALERT, CaptureWatch


class TestWhileTheCaptureAdvances:
    def test_a_file_that_grows_says_nothing(self):
        monitoring = CaptureWatch()
        assert monitoring.observe(1000) == ""
        assert monitoring.observe(2000) == ""
        assert monitoring.observe(3000) == ""

    def test_the_first_reading_concludes_nothing(self):
        """With nothing to compare against, nothing is known: keeping quiet is right."""
        assert CaptureWatch().observe(0) == ""


class TestWhenTheCaptureStops:
    """Before, a dead capture only showed at processing time, the meeting over.

    On 2026-09-09 a meeting recorded nothing at all and nothing said so: no file, no
    warning, and the loss was only discovered while looking for why the minutes
    never arrived.
    """

    def test_stillness_ends_up_raising_the_alarm(self):
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        raisons = [monitoring.observe(5000) for _ in range(TURNS_BEFORE_ALERT)]
        assert raisons[-1], "l'alerte doit finir par sortir"
        assert "n'avance plus" in raisons[-1]

    def test_it_does_not_cry_out_on_the_first_still_turn(self):
        """A write buffer emptying is not a failure."""
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        assert monitoring.observe(5000) == ""

    def test_it_says_so_only_once(self):
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        dites = [r for _ in range(10) if (r := monitoring.observe(5000))]
        assert len(dites) == 1, "répéter à chaque tour noierait le message"

    def test_starting_again_rearms_the_watch(self):
        """A change of hardware can interrupt the capture for the length of one piece."""
        monitoring = CaptureWatch()
        monitoring.observe(5000)
        for _ in range(TURNS_BEFORE_ALERT):
            monitoring.observe(5000)
        assert monitoring.observe(9000) == "", "ça repart : plus rien à dire"
        for _ in range(TURNS_BEFORE_ALERT):
            dernier = monitoring.observe(9000)
        assert dernier, "une seconde panne doit se dire aussi"

    def test_a_file_that_shrinks_counts_as_still(self):
        """It does not happen normally, so it must not pass unnoticed."""
        monitoring = CaptureWatch()
        monitoring.observe(9000)
        raisons = [monitoring.observe(1000) for _ in range(TURNS_BEFORE_ALERT)]
        assert raisons[-1]
