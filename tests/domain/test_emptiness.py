"""Ce qu'une liste vide doit dire, et ce que ses boutons peuvent faire.

Signalé à l'usage sur l'onglet « Voix » : un tableau vide sous quatre boutons
actifs. Le tableau ne disait que ce que l'œil voyait déjà, et les boutons
laissaient croire qu'il y avait quelque chose à faire.
"""

from greffier.domain.emptiness import Missing, may_act, meetings, thread, voices


class TestLesReunions:
    def test_before_the_first_one_it_says_so(self):
        assert meetings(0) is Missing.NO_MEETING_YET

    def test_a_list_with_meetings_says_nothing(self):
        assert meetings(1) is None
        assert meetings(40) is None


class TestLesVoix:
    def test_nothing_chosen_is_not_nothing_to_name(self):
        """Les deux cas sont vides, les deux phrases ne sont pas les mêmes :
        l'un demande un clic, l'autre dit que le travail est fait."""
        assert voices(a_meeting_is_chosen=False, how_many=0) is Missing.NO_MEETING_CHOSEN
        assert voices(a_meeting_is_chosen=True, how_many=0) is Missing.NO_VOICE_TO_NAME

    def test_a_meeting_chosen_without_its_voices_yet(self):
        """Une réunion choisie mais pas encore traitée : rien à nommer non plus."""
        assert voices(a_meeting_is_chosen=True, how_many=0) is Missing.NO_VOICE_TO_NAME

    def test_voices_to_name_say_nothing(self):
        assert voices(a_meeting_is_chosen=True, how_many=3) is None

    def test_nothing_chosen_wins_over_the_count(self):
        """Sans réunion choisie, le nombre de voix ne veut rien dire."""
        assert voices(a_meeting_is_chosen=False, how_many=7) is Missing.NO_MEETING_CHOSEN


class TestLeFil:
    def test_empty_until_somebody_speaks(self):
        assert thread(0) is Missing.NO_THREAD_YET

    def test_a_thread_with_turns_says_nothing(self):
        assert thread(1) is None


class TestCeQueLesBoutonsPeuvent:
    def test_nothing_missing_lets_them_act(self):
        assert may_act(None) is True

    def test_anything_missing_holds_them(self):
        for raison in Missing:
            assert may_act(raison) is False
