"""Ce que les participants doivent pouvoir savoir, et sa trace.

Une voix est une donnée biométrique. Le principe retenu : ce qui n'est pas
écrit n'a pas eu lieu, une mention orale ne se retrouve pas six mois plus
tard, une ligne dans le compte rendu si.
"""

from greffier.domain.consent import (
    MENTIONS,
    RAPPEL,
    Disclosure,
    mention,
    read,
    to_draw,
)


class TestReadingTheSetting:
    def test_the_three_states_read_back(self):
        assert read("rien") is Disclosure.NOTHING
        assert read("annoncé") is Disclosure.ANNONCE
        assert read("accord") is Disclosure.AGREEMENT

    def test_case_and_spaces_do_not_count(self):
        assert read("  Accord ") is Disclosure.AGREEMENT

    def test_an_unknown_value_falls_back_to_the_most_careful(self):
        """Une faute d'orthographe ne doit pas faire écrire que les
        participants ont donné leur accord."""
        assert read("oui") is Disclosure.NOTHING
        assert read("") is Disclosure.NOTHING


class TestWhatTheMinutesSay:
    def test_every_state_has_its_sentence(self):
        for state in Disclosure:
            assert mention(state)

    def test_nothing_said_is_said_plainly(self):
        """Prétendre le contraire serait pire que de l'avouer."""
        assert "n'a pas été tracée" in mention(Disclosure.NOTHING)

    def test_telling_them_does_not_claim_consent(self):
        sentence = mention(Disclosure.ANNONCE)
        assert "informés" in sentence
        assert "accord" not in sentence

    def test_consent_is_told_apart_from_a_notice(self):
        assert "accord" in mention(Disclosure.AGREEMENT)

    def test_all_of_them_say_the_meeting_is_recorded(self):
        for sentence in MENTIONS.values():
            assert "enregistrée" in sentence


class TestWhatIsLeftToDo:
    def test_nothing_recorded_leaves_it_to_do(self):
        assert to_draw(Disclosure.NOTHING) is True

    def test_a_recorded_notice_is_enough(self):
        assert to_draw(Disclosure.ANNONCE) is False
        assert to_draw(Disclosure.AGREEMENT) is False

    def test_the_reminder_says_why_and_what_to_do(self):
        aplati = " ".join(RAPPEL.split())
        assert "donnée biométrique" in aplati
        assert "prévenir les participants" in aplati
