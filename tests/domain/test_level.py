"""Juger un niveau de parole, pas un niveau de silence."""

from greffier.domain.level import (
    GOOD_DB,
    INSUFFICIENT_DB,
    SILENT_DB,
    Verdict,
    judge,
    say,
    sufficient,
)


class TestTheThresholds:
    def test_the_making_things_up_threshold_is_the_measured_one(self):
        """At -43 dB, « Test, test de réunion » became « Merci d'avoir
        regardé cette vidéo ! »."""
        assert INSUFFICIENT_DB == -43.0

    def test_the_silent_threshold_is_the_one_of_the_chain(self):
        """Two thresholds for the same question would end up contradicting each other."""
        from greffier.application.process import SILENT_THRESHOLD_DB

        assert SILENT_DB == SILENT_THRESHOLD_DB

    def test_the_thresholds_are_in_order(self):
        assert SILENT_DB < INSUFFICIENT_DB < GOOD_DB < 0


class TestJudgingALevel:
    def test_plain_speech_is_good(self):
        assert judge(-22.0) is Verdict.GOOD

    def test_just_under_good_is_weak(self):
        assert judge(-35.0) is Verdict.WEAK

    def test_under_the_making_things_up_threshold_it_is_too_low(self):
        assert judge(-50.0) is Verdict.INSUFFICIENT

    def test_real_silence_is_silent(self):
        assert judge(-90.0) is Verdict.SILENT

    def test_the_bounds_belong_to_the_better_verdict(self):
        assert judge(GOOD_DB) is Verdict.GOOD
        assert judge(INSUFFICIENT_DB) is Verdict.WEAK


class TestWhatIsSaidAboutIt:
    """A level with no what-to-do serves nobody."""

    def test_silent_says_where_to_look(self):
        sentence = say(-90.0)
        assert "sourdine" in sentence
        assert "autorisation micro" in sentence

    def test_too_low_says_the_model_makes_things_up(self):
        """That is the counter-intuitive fact: less signal, not less text."""
        assert "invente" in say(-50.0)

    def test_weak_says_what_a_headset_would_gain(self):
        assert "casque" in say(-35.0)

    def test_good_stays_short(self):
        assert say(-20.0) == "Bon niveau (-20 dB)."

    def test_every_sentence_carries_the_figure(self):
        for db in (-90.0, -50.0, -35.0, -20.0):
            assert f"{db:.0f} dB" in say(db)


class TestStartingAMeeting:
    def test_a_weak_level_still_starts(self):
        """A meeting that takes place beats a meeting refused."""
        assert sufficient(-35.0) is True

    def test_it_warns_under_the_making_things_up_threshold(self):
        assert sufficient(-50.0) is False
        assert sufficient(-90.0) is False


class TestWatchingDuringTheMeeting:
    """The file grows but holds almost nothing.

    Distinct from a capture that stopped advancing: here the sound arrives, too
    quiet. Saying so during the meeting leaves a chance to move the mic closer;
    finding out in the minutes leaves none.
    """

    def monitoring(self):
        from greffier.domain.level import LevelWatch

        return LevelWatch()

    def test_it_does_not_conclude_at_once(self):
        """Nobody speaks without stopping: concluding on the first reading would amount to
        raising the alarm because somebody was listening.
        """
        monitoring = self.monitoring()
        assert monitoring.observe(-60.0) == ""

    def test_a_lastingly_weak_level_ends_up_warning(self):
        from greffier.domain.level import READINGS_BEFORE_ALERT

        monitoring = self.monitoring()
        reasons = [monitoring.observe(-55.0) for _ in range(READINGS_BEFORE_ALERT)]
        assert reasons[-1]
        assert "trop faible" in reasons[-1]

    def test_one_loud_sentence_is_enough_to_reassure(self):
        """The maximum and not the average: there is silence between two sentences, and an
        average mostly measures the silences.
        """
        from greffier.domain.level import READINGS_BEFORE_ALERT

        monitoring = self.monitoring()
        monitoring.observe(-22.0)
        reasons = [monitoring.observe(-80.0) for _ in range(READINGS_BEFORE_ALERT)]
        assert not any(reasons)

    def test_it_says_so_only_once(self):
        """A level cannot be fixed without interrupting: repeating adds nothing."""
        from greffier.domain.level import READINGS_BEFORE_ALERT

        monitoring = self.monitoring()
        said_ones = [
            because
            for _ in range(READINGS_BEFORE_ALERT * 3)
            if (because := monitoring.observe(-55.0))
        ]
        assert len(said_ones) == 1

    def test_the_warning_says_the_level_and_what_to_do(self):
        from greffier.domain.level import READINGS_BEFORE_ALERT

        monitoring = self.monitoring()
        for _ in range(READINGS_BEFORE_ALERT):
            because = monitoring.observe(-55.0)
        assert "-55 dB" in because
        assert "invente" in because
