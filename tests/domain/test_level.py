"""Juger un niveau de parole, pas un niveau de silence."""

from greffier.domain.level import (
    BON_DB,
    INSUFFISANT_DB,
    MUET_DB,
    Verdict,
    judge,
    say,
    sufficient,
)


class TestTheThresholds:
    def test_the_making_things_up_threshold_is_the_measured_one(self):
        """À -43 dB, « Test, test de réunion » est devenu « Merci d'avoir
        regardé cette vidéo ! »."""
        assert INSUFFISANT_DB == -43.0

    def test_the_silent_threshold_is_the_one_of_the_chain(self):
        """Deux seuils pour la même question finiraient par se contredire."""
        from greffier.application.process import SEUIL_MUET_DB

        assert MUET_DB == SEUIL_MUET_DB

    def test_the_thresholds_are_in_order(self):
        assert MUET_DB < INSUFFISANT_DB < BON_DB < 0


class TestJudgingALevel:
    def test_plain_speech_is_good(self):
        assert judge(-22.0) is Verdict.BON

    def test_just_under_good_is_weak(self):
        assert judge(-35.0) is Verdict.FAIBLE

    def test_under_the_making_things_up_threshold_it_is_too_low(self):
        assert judge(-50.0) is Verdict.INSUFFISANT

    def test_real_silence_is_silent(self):
        assert judge(-90.0) is Verdict.MUET

    def test_the_bounds_belong_to_the_better_verdict(self):
        assert judge(BON_DB) is Verdict.BON
        assert judge(INSUFFISANT_DB) is Verdict.FAIBLE


class TestWhatIsSaidAboutIt:
    """Un niveau sans quoi-faire ne sert à personne."""

    def test_silent_says_where_to_look(self):
        sentence = say(-90.0)
        assert "sourdine" in sentence
        assert "autorisation micro" in sentence

    def test_too_low_says_the_model_makes_things_up(self):
        """C'est le fait contre-intuitif : moins de signal, pas moins de texte."""
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
        """Une réunion qui a lieu vaut mieux qu'une réunion refusée."""
        assert sufficient(-35.0) is True

    def test_it_warns_under_the_making_things_up_threshold(self):
        assert sufficient(-50.0) is False
        assert sufficient(-90.0) is False


class TestWatchingDuringTheMeeting:
    """Le fichier grossit mais ne contient presque rien.

    Distinct d'une capture qui n'avance plus : ici le son arrive, trop faible.
    Le dire pendant la réunion laisse une chance de rapprocher le micro ; le
    découvrir au compte rendu n'en laisse aucune.
    """

    def monitoring(self):
        from greffier.domain.level import LevelWatch

        return LevelWatch()

    def test_it_does_not_conclude_at_once(self):
        """Personne ne parle en continu : conclure au premier relevé
        reviendrait à alerter parce que quelqu'un écoutait."""
        monitoring = self.monitoring()
        assert monitoring.observe(-60.0) == ""

    def test_a_lastingly_weak_level_ends_up_warning(self):
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        monitoring = self.monitoring()
        raisons = [monitoring.observe(-55.0) for _ in range(RELEVES_AVANT_ALERTE)]
        assert raisons[-1]
        assert "trop faible" in raisons[-1]

    def test_one_loud_sentence_is_enough_to_reassure(self):
        """Le maximum et non la moyenne : entre deux phrases il y a du silence,
        et une moyenne mesure surtout les silences."""
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        monitoring = self.monitoring()
        monitoring.observe(-22.0)
        raisons = [monitoring.observe(-80.0) for _ in range(RELEVES_AVANT_ALERTE)]
        assert not any(raisons)

    def test_it_says_so_only_once(self):
        """Le niveau ne se corrige pas sans interrompre : répéter n'ajoute rien."""
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        monitoring = self.monitoring()
        dites = [
            because
            for _ in range(RELEVES_AVANT_ALERTE * 3)
            if (because := monitoring.observe(-55.0))
        ]
        assert len(dites) == 1

    def test_the_warning_says_the_level_and_what_to_do(self):
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        monitoring = self.monitoring()
        for _ in range(RELEVES_AVANT_ALERTE):
            because = monitoring.observe(-55.0)
        assert "-55 dB" in because
        assert "invente" in because
