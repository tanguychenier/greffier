"""The assistant's manners, covered without starting a meeting."""

from greffier.domain.participation import (
    MINIMUM_LULL,
    Because,
    Manners,
    Opening,
    called_by_name,
    is_own,
    own_words,
    speech_density,
    without_own_name,
)


def opening(because=Because.CONTRIBUTION, remark="…", born_at=0.0, subject=""):
    return Opening(because=because, remark=remark, born_at=born_at, subject=subject)


class TestNeverCuttingIn:
    def test_it_keeps_quiet_while_anyone_is_speaking(self):
        """The defect of every voice assistant: answering into the gap.

        A one-second gap in a meeting is not an invitation, it is a breath. Stepping
        into it is cutting somebody off.
        """
        manners = Manners()
        refusal = manners.refusal(opening(), now=10.0, lull=0.5)
        assert refusal == "quelqu'un parle"

    def test_a_real_lull_gives_it_the_floor(self):
        manners = Manners()
        assert manners.refusal(opening(), now=10.0, lull=MINIMUM_LULL) is None

    def test_it_does_not_slip_into_a_tight_exchange(self):
        """Three people talking in turn are not waiting for a fourth opinion."""
        manners = Manners()
        refusal = manners.refusal(opening(born_at=95.0), now=100.0, lull=3.0,
                                density=0.95)
        assert refusal == "la discussion est trop dense"


class TestNeverComingBackTooOften:
    def test_it_rests_after_speaking(self):
        manners = Manners()
        said = opening(born_at=0.0)
        manners.has_spoken(said, now=0.0)
        refusal = manners.refusal(opening(born_at=60.0), now=60.0, lull=5.0)
        assert refusal is not None and "repos" in refusal

    def test_once_the_rest_is_over_it_may_speak_again(self):
        manners = Manners(rest=180.0)
        manners.has_spoken(opening(), now=0.0)
        assert manners.refusal(opening(born_at=200.0), now=200.0, lull=5.0) is None

    def test_being_called_ignores_the_rest(self):
        """Someone addressing the tool expects an answer, not restraint."""
        manners = Manners()
        manners.has_spoken(opening(), now=0.0)
        appel = opening(because=Because.APPELE, born_at=10.0)
        assert manners.refusal(appel, now=10.0, lull=0.0, density=1.0) is None


class TestNeverRepeatingItself:
    def test_a_subject_already_dealt_with_does_not_come_back(self):
        manners = Manners()
        premiere = opening(subject="qui-parle-voix-3", born_at=10.0)
        manners.has_spoken(premiere, now=10.0)
        seconde = opening(subject="qui-parle-voix-3", born_at=400.0)
        assert manners.refusal(seconde, now=400.0, lull=5.0) == "déjà dit"

    def test_even_called_it_does_not_repeat_a_question_asked(self):
        manners = Manners()
        manners.has_spoken(opening(subject="qui-parle-voix-3"), now=0.0)
        appel = opening(because=Because.APPELE, subject="qui-parle-voix-3", born_at=50.0)
        assert manners.refusal(appel, now=50.0, lull=9.0) == "déjà dit"


class TestNeverServingSomethingCold:
    def test_a_stale_opening_is_dropped(self):
        """Coming back to a subject already left looks like an absent-minded participant."""
        manners = Manners(staleness=90.0)
        vieille = opening(born_at=10.0)
        refusal = manners.refusal(vieille, now=200.0, lull=5.0)
        assert refusal == "la conversation est passée à autre chose"

    def test_a_call_by_name_does_not_go_stale_for_all_that(self):
        manners = Manners()
        appel = opening(because=Because.APPELE, born_at=10.0)
        assert manners.refusal(appel, now=500.0, lull=0.0) is None


class TestChoosingWhatToSay:
    def test_at_most_one_opening_and_the_strongest(self):
        """The others are dropped, not held in reserve."""
        manners = Manners()
        retenue = manners.choose(
            [
                opening(because=Because.CONTRIBUTION, remark="une idée", born_at=10.0),
                opening(because=Because.INDISTINCT_VOICE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.QUESTION_WITHOUT_ANSWER,
                        remark="et Pascal ?", born_at=10.0),
            ],
            now=12.0, lull=5.0,
        )
        assert retenue is not None and retenue.remark == "qui parle ?"

    def test_on_equal_strength_the_most_recent_one_passes(self):
        manners = Manners()
        retenue = manners.choose(
            [opening(remark="vieille", born_at=10.0), opening(remark="fraîche", born_at=50.0)],
            now=60.0, lull=5.0,
        )
        assert retenue is not None and retenue.remark == "fraîche"

    def test_nothing_to_say_is_an_answer(self):
        manners = Manners()
        assert manners.choose([], now=10.0, lull=5.0) is None

    def test_being_called_comes_before_everything(self):
        manners = Manners()
        retenue = manners.choose(
            [
                opening(because=Because.INDISTINCT_VOICE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.APPELE, remark="oui ?", born_at=11.0),
            ],
            now=12.0, lull=0.0, density=1.0,
        )
        assert retenue is not None and retenue.remark == "oui ?"


class TestTheButton:
    def test_switched_off_it_says_nothing_at_all(self):
        """The button in the window sets this, and unsets it, as often as wanted."""
        manners = Manners(active=False)
        appel = opening(because=Because.APPELE, born_at=10.0)
        assert manners.refusal(appel, now=10.0, lull=9.0) == "il ne participe pas"

    def test_switched_back_on_it_starts_again_without_a_grudge(self):
        manners = Manners(active=False)
        manners.active = True
        assert manners.refusal(opening(born_at=10.0), now=11.0, lull=5.0) is None


class TestWhenSpeakingFails:
    def test_a_phrasing_that_fails_does_not_cost_the_rest(self):
        """`a_parle` s'appelle après coup : rien n'a été dit, rien n'est retenu."""
        manners = Manners()
        assert manners.refusal(opening(born_at=10.0), now=11.0, lull=5.0) is None
        assert manners.spoke_at is None


class TestHowDenseTheTalkIs:
    def test_a_full_minute_is_worth_one(self):
        assert speech_density([(0.0, 60.0)], now=60.0) == 1.0

    def test_an_empty_minute_is_worth_zero(self):
        assert speech_density([], now=60.0) == 0.0

    def test_only_the_last_minute_counts(self):
        """A meeting that comes alive must not be judged on its quiet beginning."""
        turns = [(0.0, 300.0), (350.0, 355.0)]
        assert speech_density(turns, now=360.0, window=60.0) < 0.2

    def test_a_turn_astride_counts_only_for_its_share(self):
        assert speech_density([(50.0, 70.0)], now=60.0, window=60.0) == 10.0 / 60.0


class TestWhatTheSettingGuarantees:
    """The contract as it was asked for: three sentences, three guarantees.

    "If I switch it on: it speaks only when its name is said. When we cut it, it
    does not speak. If it is speaking and we cut it, it does not finish its
    sentence."
    """

    def test_switched_on_it_speaks_only_on_its_name(self):
        """Without the initiative, no spontaneous opening gets through."""
        manners = Manners(active=True)
        idee = Opening(because=Because.CONTRIBUTION, remark="une remarque", born_at=100.0)
        appel = Opening(because=Because.APPELE, remark="oui ?", born_at=100.0)
        # L'apport n'est même pas cherché quand l'initiative est éteinte : c'est
        # la veille qui s'en charge. Ici on vérifie que l'appel, lui, passe
        # toujours — quelles que soient les conditions.
        assert manners.refusal(appel, now=100.0, lull=0.0, density=1.0) is None
        assert manners.refusal(idee, now=100.0, lull=0.0, density=1.0)

    def test_switched_off_it_says_nothing_at_all(self):
        manners = Manners(active=False)
        for because in Because:
            opening = Opening(because=because, remark="…", born_at=100.0)
            assert manners.refusal(opening, now=100.0, lull=9.0) == (
                "il ne participe pas")


class TestItMustNotHearItself:
    """It speaks through the loudspeaker, and the tool records the system output.

    That is deliberate: it is how it hears the other participants of a video call.
    As a result its own voice comes back on the others' channel, it reads its own
    name in its own answer, and off it goes again. **Without end.**

    Judged on the words and not on the clock, and that is the whole point: it
    answers late, in a separate thread, so no window of time is reliable.
    """

    DIT = "Qui prend en charge la migration en Symfony 7 ?"

    def _its_own_words(self, *remarks: str) -> list[frozenset[str]]:
        return [own_words(r) for r in remarks]

    def test_its_exact_words_come_back(self):
        assert is_own(self.DIT, self._its_own_words(self.DIT))

    def test_its_words_mangled_by_the_loudspeaker(self):
        """What comes back is never spelled the same way."""
        assert is_own(
            "qui prend en charge la migration en Symfony sept",
            self._its_own_words(self.DIT),
        )

    def test_half_of_its_sentence_is_enough(self):
        """The room and the capture loop cost words on the way."""
        assert is_own("qui prend en charge la migration", self._its_own_words(self.DIT))

    def test_the_room_is_not_taken_for_it(self):
        assert not is_own(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?",
            self._its_own_words(self.DIT),
        )

    def test_an_interjection_is_never_its_own(self):
        """"oui" and "d'accord" belong to everybody."""
        for court in ("oui", "d'accord", "bon", "ok"):
            assert not is_own(court, self._its_own_words("oui d'accord bon ok"))

    def test_having_said_nothing_it_hears_nobody(self):
        assert not is_own(self.DIT, [])

    def test_several_of_its_remarks_are_kept(self):
        """Elle parle plusieurs fois : chacun doit rester reconnaissable."""
        mes = self._its_own_words(
            self.DIT,
            "Il reste la signature, et la recette à caler.",
        )
        assert is_own("il reste la signature et la recette", mes)
        assert is_own("qui prend en charge la migration", mes)

    def test_accents_do_not_make_two_sentences(self):
        assert is_own(
            "L'ETAPE VISA EST DEJA CALEE POUR JEUDI",
            self._its_own_words("L'étape visa est déjà calée pour jeudi"),
        )

    def test_a_shared_subject_is_not_enough(self):
        """The real risk: a participant talking about the same subject it did."""
        assert not is_own(
            "la migration me paraît risquée avant la recette de jeudi soir",
            self._its_own_words("Qui prend en charge la migration ?"),
        )


class TestItsOwnNameNeverLeavesItsMouth:
    """The hard guarantee, and the one that cuts the loop at the root.

    Seen in a real meeting: "Lucie, est-ce que tu peux faire des recherches sur
    Internet ?" fifteen times in fifteen seconds, spoken by it. It had repeated
    the question it had just been asked, its own name included, heard it through
    the capture loop, read its name in it, and set off again.

    Taking its name out of everything it pronounces makes the cycle impossible,
    whatever else happens: no brain, a mangled transcription, a badly attributed
    channel.
    """

    def test_its_name_is_taken_out(self):
        assert "Lucie" not in without_own_name(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?", "Lucie"
        )

    def test_what_it_says_stays_readable(self):
        assert without_own_name(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?", "Lucie"
        ) == "est-ce que tu peux faire des recherches sur Internet ?"

    def test_its_mangled_name_is_taken_out_too(self):
        """La transcription rend « Lucie » de vingt façons."""
        for said in ("Lucy, tu m'entends ?", "Lucie tu m'entends ?",
                    "Luci, tu m'entends ?"):
            assert "uc" not in without_own_name(said, "Lucie").lower(), said

    def test_a_remark_without_its_name_is_untouched(self):
        """The common case: it must not see its own sentence reworked."""
        propos = "Qui prend en charge la migration en Symfony 7 ?"
        assert without_own_name(propos, "Lucie") == propos

    def test_french_typography_survives(self):
        """Le français garde une espace avant les deux-points."""
        propos = "Merci, c'est noté : je mets Hubert sur cette voix."
        assert without_own_name(propos, "Lucie") == propos

    def test_the_name_in_the_middle_of_a_sentence(self):
        assert without_own_name("Oui Lucie a bien compris", "Lucie") == "Oui a bien compris"

    def test_an_empty_name_touches_nothing(self):
        assert without_own_name("phrase entière", "") == "phrase entière"

    def test_what_is_left_calls_nobody_any_more(self):
        """Le bouclage complet : ce qu'elle dit ne doit plus l'appeler."""
        for question in (
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?",
            "Lucie, tu as compris le sujet Lucie ?",
            "Dis-moi Lucie",
        ):
            remaining = without_own_name(question, "Lucie")
            assert not called_by_name(remaining, "Lucie"), remaining


class TestItOnlyAnswersToItsOwnName:
    """It spoke up believing it had been called, and made the room look foolish.

    Measured on 3 809 turns of real meetings, with a five-letter first name: the
    old rule allowed two edits whatever the length, so "lui" named it. **113
    times**, against 75 real calls. Two guards, and each was chosen from that
    measurement rather than from taste.
    """

    def test_the_word_that_cost_the_most_is_refused(self):
        """"lui" is at two edits from "Lucie", and it is a common French word."""
        assert not called_by_name("je lui ai dit qu'on se cale jeudi", "Lucie")

    def test_its_own_name_is_still_heard(self):
        assert called_by_name("Lucie, est-ce que tu nous entends ?", "Lucie")

    def test_a_name_in_the_middle_of_a_sentence_is_heard(self):
        assert called_by_name("on demande à Lucie de vérifier", "Lucie")

    def test_a_lightly_mangled_name_is_still_heard(self):
        """The transcription does not always spell it right."""
        assert called_by_name("Lucye, tu peux regarder ?", "Lucie")

    def test_a_lowercase_word_never_names_it(self):
        """Every one of the 75 real calls was written with a capital, and no
        word that named it wrongly ever was: a first name is a proper noun."""
        assert not called_by_name("on parle de lucie demain", "Lucie")

    def test_a_short_name_demands_more(self):
        """A single edit on three letters is a third of the word."""
        assert called_by_name("Zoé, tu en penses quoi ?", "Zoé")
        assert not called_by_name("Zone rouge sur le planning", "Zoé")

    def test_a_long_name_may_be_mangled_more(self):
        assert called_by_name("Arnaude, tu peux regarder ?", "Arnaud")

    def test_an_empty_name_names_nobody(self):
        assert not called_by_name("Lucie, tu es là ?", "   ")

    def test_taking_the_name_out_stays_generous(self):
        """Stripping is not answering: leaving a mangled name in what it says is
        what made it call itself, and taking out a word that was not its name
        costs nothing."""
        assert "uc" not in without_own_name("Lucy, je regarde.", "Lucie").lower()
