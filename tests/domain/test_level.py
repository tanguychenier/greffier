"""Juger un niveau de parole, pas un niveau de silence."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greffier.domain.level import (
    GOOD_DB,
    INSUFFICIENT_DB,
    READINGS_BEFORE_ALERT,
    SILENT_DB,
    LevelWatch,
    Verdict,
    judge,
    say,
    sufficient,
)

#: Levels a capture can report: a sound card never says more than 0 dBFS, and
#: -200 is well under anything a microphone can hear.
levels = st.floats(min_value=-200.0, max_value=0.0, allow_nan=False, allow_infinity=False)

#: The verdicts from the worst to the best, to compare two of them.
FROM_WORST_TO_BEST = (Verdict.SILENT, Verdict.INSUFFICIENT, Verdict.WEAK, Verdict.GOOD)

#: For the properties written as methods. mutmut runs the suite several times
#: in one process, so a method runs on several instances of its class, which
#: Hypothesis takes for different executors and refuses; a refused property
#: then counts as a kill for every mutant it touches. The profile's own
#: suppression stays alongside.
PROPERTY = settings(
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.differing_executors]
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
        assert judge(SILENT_DB) is Verdict.INSUFFICIENT

    @PROPERTY
    @given(levels, st.floats(min_value=0.0, max_value=100.0))
    def test_turning_the_gain_up_never_worsens_the_verdict(self, db, gain):
        """Four verdicts, one ordering: a louder capture is never judged worse."""
        before = FROM_WORST_TO_BEST.index(judge(db))
        after = FROM_WORST_TO_BEST.index(judge(db + gain))
        assert after >= before


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

    def test_silent_is_said_in_full(self):
        """The sentence is what the person reads: every word of it counts."""
        assert say(-90.0) == (
            "Rien n'est capté (-90 dB). Vérifie le bouton de sourdine du "
            "casque, le micro choisi, puis l'autorisation micro dans les "
            "réglages du système."
        )

    def test_too_low_is_said_in_full(self):
        assert say(-50.0) == (
            "Trop faible pour transcrire (-50 dB). À ce niveau, le modèle "
            "n'écrit pas moins bien : il invente. Rapproche le micro, monte son "
            "gain, ou prends un casque avant de démarrer."
        )

    def test_weak_is_said_in_full(self):
        assert say(-35.0) == (
            "Faible (-35 dB). La réunion sera transcrite, mais des mots "
            "seront perdus ou déformés. Un casque porté suffit généralement à "
            "gagner vingt décibels."
        )

    def test_every_sentence_carries_the_figure(self):
        for db in (-90.0, -50.0, -35.0, -20.0):
            assert f"{db:.0f} dB" in say(db)

    @PROPERTY
    @given(levels)
    def test_the_figure_is_the_level_rounded_to_the_decibel(self, db):
        """A tenth of a decibel means nothing to anybody; the whole figure does."""
        assert f"({db:.0f} dB)" in say(db)


class TestStartingAMeeting:
    def test_a_weak_level_still_starts(self):
        """A meeting that takes place beats a meeting refused."""
        assert sufficient(-35.0) is True

    def test_it_warns_under_the_making_things_up_threshold(self):
        assert sufficient(-50.0) is False
        assert sufficient(-90.0) is False

    @PROPERTY
    @given(levels)
    def test_recording_starts_exactly_where_the_model_stops_inventing(self, db):
        """One threshold decides both: the verdict and whether to start."""
        assert sufficient(db) is (db >= INSUFFICIENT_DB)


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

    def test_the_warning_is_the_best_level_then_the_advice(self):
        """The best level heard so far, not the last one: that is what the person
        can compare with the "-43 dB" the advice is about.
        """
        monitoring = self.monitoring()
        monitoring.observe(-55.0)
        for _ in range(READINGS_BEFORE_ALERT - 1):
            because = monitoring.observe(-80.0)
        assert because == (
            "Le son capté reste trop faible (-55 dB au plus haut depuis le "
            "début). " + say(-55.0)
        )

    @PROPERTY
    @given(st.lists(levels, min_size=READINGS_BEFORE_ALERT, max_size=3 * READINGS_BEFORE_ALERT))
    def test_it_warns_once_at_the_eighth_reading_or_never(self, readings):
        """What the first readings reached decides everything: the best level
        can only rise afterwards, so a meeting that passed the bar once never
        hears of it, and one that did not hears of it exactly once.
        """
        monitoring = LevelWatch()
        said = [monitoring.observe(db) for db in readings]
        best_at_first = max(readings[:READINGS_BEFORE_ALERT])
        if sufficient(best_at_first):
            assert said == [""] * len(readings)
        else:
            assert [i for i, because in enumerate(said) if because] == [READINGS_BEFORE_ALERT - 1]
            assert f"({best_at_first:.0f} dB au plus haut" in said[READINGS_BEFORE_ALERT - 1]
