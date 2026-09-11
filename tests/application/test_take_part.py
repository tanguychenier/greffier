"""How the assistant behaves in a meeting, with no sound and no model."""

from greffier.application.take_part import AssistantSettings, Remark
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Manners, Opening, own_words


def said(text, start=10.0, end=12.0):
    return Utterance(span=Span(start, end), text=text)


class FakeVoiceAdapter:
    def __init__(self, marche=True):
        self.marche = marche
        self.remark = []

    def say(self, text):
        self.remark.append(text)
        return self.marche

    def go_quiet(self):
        ...

    def is_speaking(self):
        return False


class FakeBrain:
    """Like `ClaudeWriter`: it carries guidance that gets replaced.

    The attribute matters: `_interrogate` uses it to set guidance for the length of
    one call, and falls back to a prefix when it does not exist. A double without
    it would not exercise the real path.
    """

    def __init__(self, response="Oui, je vous entends très bien."):
        self.response = response
        self.consignes_propres = ""
        self.requests = []
        #: The guidance in force at each call, and not at the end: it is put
        #: back afterwards, so reading it later says nothing.
        self.consignes_vues = []

    def write_up(self, text):
        self.requests.append(text)
        self.consignes_vues.append(self.consignes_propres)
        return self.response


class TestBeingCalledByName:
    def test_its_name_said_out_loud_makes_it_answer(self):
        """"Lucie, est-ce que tu nous entends ?" — the case being demonstrated."""
        assistant = AssistantSettings(name="Lucie")
        retenue = assistant.turn([said("Lucie, est-ce que tu nous entends bien ?")],
                                 now=13.0)
        assert retenue is not None
        assert retenue.because is Because.APPELE
        assert retenue.remark == "est-ce que tu nous entends bien ?"

    def test_it_answers_with_its_voice_and_leaves_a_trace(self):
        traces = []
        voice, cerveau = FakeVoiceAdapter(), FakeBrain()
        assistant = AssistantSettings(name="Lucie", voice=voice, cerveau=cerveau,
                                tracer=lambda who, what: traces.append((who, what)))
        opening = Opening(because=Because.APPELE, remark="tu nous entends ?", born_at=10.0)
        rendered = assistant.answer(opening, now=13.0)
        assert rendered.prononce
        assert voice.remark == ["Oui, je vous entends très bien."]
        assert traces == [("lucie", "Oui, je vous entends très bien.")]

    def test_with_no_voice_it_still_takes_part_in_writing(self):
        """Not everybody wants a voice in the room."""
        traces = []
        assistant = AssistantSettings(name="Lucie", cerveau=FakeBrain(),
                                tracer=lambda who, what: traces.append(what))
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert not rendered.prononce and traces == ["Oui, je vous entends très bien."]

    def test_an_ordinary_meeting_does_not_make_it_speak(self):
        """The common case, by far: it has nothing to say."""
        assistant = AssistantSettings(name="Lucie")
        assert assistant.turn([said("on passe au point suivant")], now=13.0) is None


class TestNotHearingItself:
    """Its voice leaves through the loudspeaker and comes back through the capture.

    Judged on its **words**, and not on a window of time. The window was estimated
    from the length of the text, and the conversation harness showed what it cost:
    it swallowed the next question, so the room went unheard. It now decides only
    for a remark too short to be judged on its words.
    """

    def test_what_it_has_just_said_does_not_come_back_to_it(self):
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_words.append(
            (9.0, own_words("Oui, je peux répéter ce qui vient d'être décidé."))
        )
        retenue = assistant.turn(
            [said("oui je peux répéter ce qui vient d'être décidé", 10.0, 12.0)],
            now=16.0,
        )
        assert retenue is None

    def test_a_question_from_the_room_reaches_it(self):
        """Even right after it has spoken: that is the other half of the problem."""
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_words.append((9.0, own_words("Oui, je vous entends.")))
        assert assistant.turn([said("Lucie, tu peux répéter ?", 10.0, 12.0)],
                              now=13.0) is not None

    def test_too_short_an_echo_is_caught_by_the_clock(self):
        """"Oui" has too few words to be judged: the window serves there."""
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_turns.append((9.0, 15.0))
        assert assistant._is_his_own(said("oui", 10.0, 12.0), 16.0)

    def test_the_window_no_longer_decides_when_the_words_suffice(self):
        """The measured defect: it swallowed the next question."""
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_turns.append((9.0, 15.0))
        assert not assistant._is_his_own(
            said("Lucie, et où en est la migration en Symfony sept ?", 10.0, 14.0),
            16.0,
        )


class TestTheCycleThatEarnsItsPlace:
    def test_it_asks_who_is_speaking_then_names_the_voice_and_thanks_them(self):
        """Asking costs one sentence and earns a name in the minutes."""
        nommees = []
        assistant = AssistantSettings(
            name="Lucie",
            name_voice=lambda voice, first_name: (nommees.append((voice, first_name)), True)[1],
        )
        question = assistant.ask_who_is_speaking("12", now=100.0)
        assistant.awaiting = question
        suite = assistant.turn([said("c'est Michel", 104.0, 105.0)], now=108.0)
        assert nommees == [("12", "Michel")]
        assert suite is not None
        assert suite.remark == "Merci, c'est noté : je mets Michel sur cette voix."

    def test_an_answer_it_cannot_make_out_names_nobody(self):
        """Better to name nobody than to call somebody "Alors"."""
        nommees = []
        assistant = AssistantSettings(
            name="Lucie", name_voice=lambda v, p: (nommees.append((v, p)), True)[1])
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([said("alors attends je ne sais plus", 104.0, 106.0)],
                               now=108.0)
        assert nommees == [] and suite is None

    def test_the_question_does_not_wait_for_ever(self):
        """Any sentence closes the wait: nothing watches for ever."""
        assistant = AssistantSettings(name="Lucie", name_voice=lambda v, p: True)
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        assistant.turn([said("bon, on reprend", 104.0, 106.0)], now=108.0)
        assert assistant.awaiting is None

    def test_asking_who_is_speaking_needs_no_model(self):
        """This question has to be immediate: nothing remote phrases it."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter())
        question = assistant.ask_who_is_speaking("7", now=50.0)
        rendered = assistant.answer(question, now=50.0)
        assert "prénom" in rendered.remark and assistant.cerveau is None


class TestManners:
    def test_it_does_not_cut_anyone_off(self):
        """The lull is measured from the end of the last utterance heard.

        On a spontaneous opening: being called overrides it, and that is deliberate.
        Someone addressing the tool is not waiting for it to judge the moment.
        """
        assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=2.0))
        idee = Opening(because=Because.CONTRIBUTION, remark="une idée", born_at=11.0)
        # The sentence ends at 12 s and we are at 12.5 s: someone is still speaking.
        assert assistant.turn([said("on continue", 11.0, 12.0)], now=12.5,
                              occasions=[idee]) is None

    def test_being_called_overrides_the_lull(self):
        assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=2.0))
        assert assistant.turn([said("Lucie ?", 11.0, 12.0)], now=12.5) is not None

    def test_the_rest_does_not_block_a_call(self):
        assistant = AssistantSettings(name="Lucie")
        assistant.manners.has_spoken(
            Opening(because=Because.CONTRIBUTION, remark="…"), now=0.0)
        assert assistant.turn([said("Lucie ?", 10.0, 11.0)], now=20.0) is not None

    def test_switched_off_it_says_nothing_at_all(self):
        assistant = AssistantSettings(name="Lucie", manners=Manners(active=False))
        assert assistant.turn([said("Lucie ?", 10.0, 11.0)], now=14.0) is None


class TestWhenThingsFail:
    def test_a_silent_brain_makes_it_pronounce_nothing(self):
        class Broken:
            def write_up(self, _):
                raise RuntimeError("modèle absent")

        voice = FakeVoiceAdapter()
        assistant = AssistantSettings(name="Lucie", voice=voice, cerveau=Broken())
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert rendered == Remark(remark="", because=Because.APPELE, a=2.0)
        assert voice.remark == []

    def test_a_phrasing_that_fails_still_leaves_the_written_trace(self):
        """What it had to say is not lost because the sound failed."""
        traces = []
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(marche=False),
                                cerveau=FakeBrain(),
                                tracer=lambda who, what: traces.append(what))
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert not rendered.prononce and traces == ["Oui, je vous entends très bien."]


class TestARemarkAlreadyWrittenGoesThroughNobody:
    """A sentence written to be said has nothing to gain from a round trip.

    The thanks that name the voice, "je mets Hugo sur cette voix", used to go
    through the model, which replaced them with a vague courtesy and lost the one
    piece of information that mattered.
    """

    def test_the_thanks_are_pronounced_word_for_word(self):
        voice, cerveau = FakeVoiceAdapter(), FakeBrain("Parfait, je vous laisse.")
        assistant = AssistantSettings(
            name="Lucie", voice=voice, cerveau=cerveau,
            name_voice=lambda _v, _p: True,
        )
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([said("c'est Hugo", 104.0, 105.0)], now=108.0)
        assert suite is not None
        rendered = assistant.answer(suite, now=108.0)
        assert rendered.remark == "Merci, c'est noté : je mets Hugo sur cette voix."
        assert cerveau.requests == [], "le modèle a été appelé pour rien"

    def test_the_question_about_a_voice_does_not_go_through_either(self):
        """It has to be immediate: nothing remote phrases it."""
        cerveau = FakeBrain("autre chose")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau)
        question = assistant.ask_who_is_speaking("7", now=50.0)
        rendered = assistant.answer(question, now=50.0)
        assert "prénom" in rendered.remark and cerveau.requests == []

    def test_a_real_question_always_goes_through_the_model(self):
        cerveau = FakeBrain("Oui, je vous entends.")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau,
                                context=lambda: "réunion")
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="tu nous entends ?", born_at=1.0),
            now=2.0)
        assert rendered.remark == "Oui, je vous entends." and len(cerveau.requests) == 1


class TestTheExchangeGoesOn:
    """Asking a question then staying mute when answered looks absent-minded, and
    leaves whoever answered wondering whether they were heard.
    """

    def test_it_reacts_to_the_answer_it_is_given(self):
        cerveau = FakeBrain("Très bien, donc c'est Hugo qui s'en occupe.")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([said("c'est Hugo qui prend", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert suite.remark == "Très bien, donc c'est Hugo qui s'en occupe."
        assert suite.as_is, "une suite déjà formulée ne repasse pas par le modèle"

    def test_the_question_asked_is_given_to_the_model(self):
        """Without it, it would react to an answer whose question it does not know."""
        cerveau = FakeBrain("…")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([said("Hugo", 104.0, 106.0)], now=109.0)
        assert any("Qui porte la migration ?" in c for c in cerveau.consignes_vues)

    def test_a_nothing_makes_it_go_quiet(self):
        """Two more remarks would make it one participant too many."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                cerveau=FakeBrain("RIEN"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assert assistant.turn([said("bon, on passe", 104.0, 106.0)],
                              now=109.0) is None

    def test_with_no_brain_it_does_not_go_on(self):
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter())
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        assert assistant.turn([said("Hugo", 104.0, 106.0)], now=109.0) is None

    def test_it_does_not_wait_for_ever(self):
        """Any sentence closes the wait: nothing watches for ever."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                cerveau=FakeBrain("RIEN"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        assistant.turn([said("autre chose", 104.0, 106.0)], now=109.0)
        assert assistant.awaiting is None


class TestItGoesOnWhileItHasQuestions:
    """A dialogue, not a round trip.

    The stopping signal comes from it, the final question mark, and not from a
    counter that would cut it off in the middle of a subject.
    """

    def test_a_follow_up_question_keeps_the_exchange_open(self):
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            cerveau=FakeBrain("Et qui valide, une fois que c'est fait ?"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([said("Hugo s'en charge", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert assistant.awaiting is suite, "l'échange s'est refermé trop tôt"

    def test_a_conclusion_closes_the_exchange(self):
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            cerveau=FakeBrain("Très bien, c'est noté."))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([said("Hugo s'en charge", 104.0, 106.0)], now=109.0)
        assert assistant.awaiting is None

    def test_the_rest_does_not_cut_an_exchange_under_way(self):
        """An answer to its own question overrides the rest.

        Otherwise the assistant would ask a question then refuse to hear the answer
        for three minutes, which is worse than asking nothing.
        """
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            cerveau=FakeBrain("Et pour quand ?"))
        assistant.manners.has_spoken(
            Opening(because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0),
            now=100.0)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        suite = assistant.turn([said("Hugo", 104.0, 106.0)], now=109.0)
        assert suite is not None, "le repos a coupé l'échange"


class TestTheLoopCannotHappen:
    """The cases nobody had thought of, and that a meeting found.

    It speaks through the loudspeaker, and the tool records the system output on
    purpose, which is how it hears the others on a video call. Its voice therefore
    comes back on the others' channel. Each guard below would be enough on its
    own; together they make the cycle impossible, whatever else happens.
    """

    QUESTION = "Lucie, est-ce que tu peux faire des recherches sur Internet ?"

    def _her(self, cerveau=None, voice=None):
        return AssistantSettings(
            name="Lucie", cerveau=cerveau, voice=voice,
            manners=Manners(creux_minimal=0.0),
        )

    def test_with_no_brain_it_keeps_quiet_instead_of_repeating(self):
        """It repeated the question, its own name included, and so called itself."""
        elle = self._her()
        rendu = elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        assert rendu.remark == ""

    def test_what_it_says_never_carries_its_own_name(self):
        class CerveauQuiRepete:
            def write_up(self, _demande):
                return "Lucie ne peut pas chercher sur Internet."

        voice = FakeVoiceAdapter()
        elle = self._her(cerveau=CerveauQuiRepete(), voice=voice)
        rendu = elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        assert "Lucie" not in rendu.remark
        assert voice.remark and "Lucie" not in voice.remark[0]

    def test_it_does_not_react_to_its_own_words(self):
        """The exact case: its sentence comes back through the capture loop."""
        class Cerveau:
            def write_up(self, _demande):
                return "Je n'ai pas accès à Internet depuis cette réunion."

        elle = self._her(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        revenu = [said("Je n'ai pas accès à Internet depuis cette réunion.", 10.0, 14.0)]
        assert elle.turn(revenu, 15.0) is None

    def test_a_mangled_transcription_of_its_words_does_not_call_it(self):
        class Cerveau:
            def write_up(self, _demande):
                return "Je n'ai pas accès à Internet depuis cette réunion."

        elle = self._her(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        abime = [said("je n ai pas acces a internet depuis cette", 10.0, 14.0)]
        assert elle.turn(abime, 15.0) is None

    def test_the_room_is_still_heard(self):
        """The guard must not make it deaf: that is the whole difficulty."""
        class Cerveau:
            def write_up(self, _demande):
                return "Je n'ai pas accès à Internet."

        elle = self._her(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        de_la_salle = [said("Lucie, tu peux nous rappeler la date ?", 20.0, 24.0)]
        retenue = elle.turn(de_la_salle, 25.0)
        assert retenue is not None and retenue.because is Because.APPELE

    def test_it_forgets_its_words_after_a_while(self):
        """Otherwise a participant restating their idea would be taken for it."""
        class Cerveau:
            def write_up(self, _demande):
                return "La migration en Symfony sept reste à confier à quelqu'un."

        elle = self._her(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark="Lucie, où en est la migration ?",
                    born_at=1.0),
            2.0,
        )
        tard = [said("la migration en Symfony sept reste à confier à quelqu'un", 600.0, 606.0)]
        assert elle._is_his_own(tard[0], 610.0) is False


class TestItMaySearch:
    """It said it could not search the web, with the tools in hand.

    Reported after a meeting. `WebSearch` and `WebFetch` were indeed granted,
    `conversation.recherche_web` being true by default, but the **spoken**
    guidance, which replaces the one for the written conversation, told it to stick
    to what had been said. It obeyed.
    """

    def test_the_spoken_guidance_allows_searching(self):
        from greffier.application.take_part import CONSIGNES_ORALES

        consigne = CONSIGNES_ORALES.format(name="Lucie")
        assert "chercher en ligne" in consigne
        assert "de ton propre chef" in consigne

    def test_it_names_the_source_without_saying_the_address(self):
        """A URL cannot be heard; a source with no name cannot be checked."""
        from greffier.application.take_part import CONSIGNES_ORALES

        consigne = CONSIGNES_ORALES.format(name="Lucie")
        assert "nomme la source à voix haute" in consigne
        assert "jamais son" in consigne and "adresse" in consigne

    def test_it_no_longer_has_to_stick_to_the_meeting(self):
        ancien = "Si tu n'as pas la réponse dans ce qui a été dit, dis-le"
        from greffier.application.take_part import CONSIGNES_ORALES

        assert ancien not in CONSIGNES_ORALES

    def test_the_tools_are_granted_when_the_setting_says_so(self):
        from greffier.adapters.configuration import Config
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.wiring import assistant

        cerveau = assistant(Config(conversation={"recherche_web": True}))
        assert isinstance(cerveau, ClaudeWriter)
        assert cerveau.tools == ClaudeWriter.SEARCH_TOOLS

    def test_the_setting_really_takes_them_away(self):
        """Whoever wants nothing to leave the machine must be able to have that."""
        from greffier.adapters.configuration import Config
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.wiring import assistant

        cerveau = assistant(Config(conversation={"recherche_web": False}))
        assert isinstance(cerveau, ClaudeWriter)
        assert cerveau.tools == ()


class TestStoppedForGood:
    """`stop()` is the end of the meeting, and it must reach a remark in flight.

    Phrasing happens in a separate thread and takes seconds: cutting the
    speaker is not enough, because the thread comes back afterwards and speaks
    into a room where the meeting is over.
    """

    def _her(self, cerveau=None):
        return AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau or FakeBrain(),
            manners=Manners(active=True),
        )

    def _a_call(self, now=12.0):
        return Opening(because=Because.APPELE, remark="Lucie, une idée ?", born_at=now)

    def test_nothing_is_pronounced_after_a_stop(self):
        elle = self._her()
        elle.stop()
        assert elle.answer(self._a_call(), now=12.0).remark == ""
        assert elle.voice.remark == []

    def test_the_speaker_is_cut_by_the_stop(self):
        elle = self._her()
        coupee = []
        elle.voice.go_quiet = lambda: coupee.append(True)
        elle.stop()
        assert coupee == [True]

    def test_a_remark_phrased_during_the_stop_stays_in(self):
        """The thread was already inside the brain when the meeting ended."""
        elle = self._her()

        class BrainThatEnds(FakeBrain):
            def write_up(self, text):
                elle.stop()
                return super().write_up(text)

        elle.cerveau = BrainThatEnds()
        assert elle.answer(self._a_call(), now=12.0).remark == ""
        assert elle.voice.remark == []

    def test_a_stop_without_a_voice_does_not_raise(self):
        elle = self._her()
        elle.voice = None
        elle.stop()
        assert elle.stopped

    def test_a_speaker_that_fails_to_stop_does_not_raise(self):
        """The neural voice goes through a subprocess: killing it can fail."""
        elle = self._her()

        def tomber():
            raise OSError("kill: no such process")

        elle.voice.go_quiet = tomber
        elle.stop()
        assert elle.stopped

    def test_before_the_stop_she_does_answer(self):
        elle = self._her()
        assert elle.answer(self._a_call(), now=12.0).remark
        assert elle.voice.remark


class TestSheKnowsTheSetting:
    """The glossary of the organisation goes to the assistant, not only to the
    writer of the minutes.

    This room says "CASA", "visa", "OTP" and "recette" for things no general
    model knows, and the writer has been told about them since the beginning
    while the assistant answered on the words alone.
    """

    def _her(self, milieu=None):
        return AssistantSettings(
            name="Lucie", cerveau=FakeBrain(), manners=Manners(active=True),
            setting=milieu,
        )

    def test_the_glossary_opens_the_guidance(self):
        elle = self._her(lambda: "[Contexte] CASA : gestion des logements.\n\n")
        consignes = elle.guidance()
        assert consignes.startswith("[Contexte] CASA")
        assert "Lucie" in consignes, "elle garde ses propres consignes"

    def test_without_a_setting_the_guidance_does_not_change(self):
        assert "Contexte" not in self._her().guidance()

    def test_an_empty_setting_adds_nothing(self):
        assert self._her(lambda: "").guidance() == self._her().guidance()

    def test_a_setting_that_fails_to_read_does_not_silence_her(self):
        """The context file can be missing or unreadable: she still answers."""

        def tomber():
            raise OSError("contexte.toml illisible")

        consignes = self._her(tomber).guidance()
        assert "Lucie" in consignes and consignes

    def test_the_setting_is_read_when_asked_for_and_not_before(self):
        """It is read at each call, so a term added mid-meeting is taken in."""
        appels = []
        elle = self._her(lambda: appels.append(1) or "[Contexte] X.\n\n")
        assert not appels
        elle.guidance()
        elle.guidance()
        assert len(appels) == 2
