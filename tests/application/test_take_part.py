"""How the assistant behaves in a meeting, with no sound and no model."""

from greffier.application.take_part import NOTHING, AssistantSettings, Remark
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Manners, Opening, own_words


def said(text, start=10.0, end=12.0):
    return Utterance(span=Span(start, end), text=text)


class FakeVoiceAdapter:
    def __init__(self, works=True):
        self.works = works
        self.remark = []

    def say(self, text):
        self.remark.append(text)
        return self.works

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
        self.own_guidance = ""
        self.requests = []
        #: The guidance in force at each call, and not at the end: it is put
        #: back afterwards, so reading it later says nothing.
        self.guidance_seen = []

    def write_up(self, text):
        self.requests.append(text)
        self.guidance_seen.append(self.own_guidance)
        return self.response


class TestBeingCalledByName:
    def test_its_name_said_out_loud_makes_it_answer(self):
        """"Lucie, est-ce que tu nous entends ?", the case being demonstrated."""
        assistant = AssistantSettings(name="Lucie")
        retained = assistant.turn([said("Lucie, est-ce que tu nous entends bien ?")],
                                 now=13.0)
        assert retained is not None
        assert retained.because is Because.CALLED
        assert retained.remark == "est-ce que tu nous entends bien ?"

    def test_it_answers_with_its_voice_and_leaves_a_trace(self):
        traces = []
        voice, brain = FakeVoiceAdapter(), FakeBrain()
        assistant = AssistantSettings(name="Lucie", voice=voice, brain=brain,
                                tracer=lambda who, what: traces.append((who, what)))
        opening = Opening(because=Because.CALLED, remark="tu nous entends ?", born_at=10.0)
        rendered = assistant.answer(opening, now=13.0)
        assert rendered.pronounced
        assert voice.remark == ["Oui, je vous entends très bien."]
        assert traces == [("lucie", "Oui, je vous entends très bien.")]

    def test_with_no_voice_it_still_takes_part_in_writing(self):
        """Not everybody wants a voice in the room."""
        traces = []
        assistant = AssistantSettings(name="Lucie", brain=FakeBrain(),
                                tracer=lambda who, what: traces.append(what))
        rendered = assistant.answer(
            Opening(because=Because.CALLED, remark="?", born_at=1.0), now=2.0)
        assert not rendered.pronounced and traces == ["Oui, je vous entends très bien."]

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
        retained = assistant.turn(
            [said("oui je peux répéter ce qui vient d'être décidé", 10.0, 12.0)],
            now=16.0,
        )
        assert retained is None

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
        named_ones = []
        assistant = AssistantSettings(
            name="Lucie",
            name_voice=lambda voice, first_name: (named_ones.append((voice, first_name)), True)[1],
        )
        question = assistant.ask_who_is_speaking("12", now=100.0)
        assistant.awaiting = question
        suite = assistant.turn([said("c'est Marcel", 104.0, 105.0)], now=108.0)
        assert named_ones == [("12", "Marcel")]
        assert suite is not None
        assert suite.remark == "Merci, c'est noté : je mets Marcel sur cette voix."

    def test_an_answer_it_cannot_make_out_names_nobody(self):
        """Better to name nobody than to call somebody "Alors"."""
        named_ones = []
        assistant = AssistantSettings(
            name="Lucie", name_voice=lambda v, p: (named_ones.append((v, p)), True)[1])
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([said("alors attends je ne sais plus", 104.0, 106.0)],
                               now=108.0)
        assert named_ones == [] and suite is None

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
        assert "prénom" in rendered.remark and assistant.brain is None


class TestManners:
    def test_it_does_not_cut_anyone_off(self):
        """The lull is measured from the end of the last utterance heard.

        On a spontaneous opening: being called overrides it, and that is deliberate.
        Someone addressing the tool is not waiting for it to judge the moment.
        """
        assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=2.0))
        idea = Opening(because=Because.CONTRIBUTION, remark="une idée", born_at=11.0)
        # The sentence ends at 12 s and we are at 12.5 s: someone is still speaking.
        assert assistant.turn([said("on continue", 11.0, 12.0)], now=12.5,
                              occasions=[idea]) is None

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
        assistant = AssistantSettings(name="Lucie", voice=voice, brain=Broken())
        rendered = assistant.answer(
            Opening(because=Because.CALLED, remark="?", born_at=1.0), now=2.0)
        assert rendered == Remark(remark="", because=Because.CALLED, a=2.0)
        assert voice.remark == []

    def test_a_phrasing_that_fails_still_leaves_the_written_trace(self):
        """What it had to say is not lost because the sound failed."""
        traces = []
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(works=False),
                                brain=FakeBrain(),
                                tracer=lambda who, what: traces.append(what))
        rendered = assistant.answer(
            Opening(because=Because.CALLED, remark="?", born_at=1.0), now=2.0)
        assert not rendered.pronounced and traces == ["Oui, je vous entends très bien."]


class TestARemarkAlreadyWrittenGoesThroughNobody:
    """A sentence written to be said has nothing to gain from a round trip.

    The thanks that name the voice, "je mets Hubert sur cette voix", used to go
    through the model, which replaced them with a vague courtesy and lost the one
    piece of information that mattered.
    """

    def test_the_thanks_are_pronounced_word_for_word(self):
        voice, brain = FakeVoiceAdapter(), FakeBrain("Parfait, je vous laisse.")
        assistant = AssistantSettings(
            name="Lucie", voice=voice, brain=brain,
            name_voice=lambda _v, _p: True,
        )
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([said("c'est Hubert", 104.0, 105.0)], now=108.0)
        assert suite is not None
        rendered = assistant.answer(suite, now=108.0)
        assert rendered.remark == "Merci, c'est noté : je mets Hubert sur cette voix."
        assert brain.requests == [], "le modèle a été appelé pour rien"

    def test_the_question_about_a_voice_does_not_go_through_either(self):
        """It has to be immediate: nothing remote phrases it."""
        brain = FakeBrain("autre chose")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), brain=brain)
        question = assistant.ask_who_is_speaking("7", now=50.0)
        rendered = assistant.answer(question, now=50.0)
        assert "prénom" in rendered.remark and brain.requests == []

    def test_a_real_question_always_goes_through_the_model(self):
        brain = FakeBrain("Oui, je vous entends.")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), brain=brain,
                                context=lambda: "réunion")
        rendered = assistant.answer(
            Opening(because=Because.CALLED, remark="tu nous entends ?", born_at=1.0),
            now=2.0)
        assert rendered.remark == "Oui, je vous entends." and len(brain.requests) == 1


class TestTheExchangeGoesOn:
    """Asking a question then staying mute when answered looks absent-minded, and
    leaves whoever answered wondering whether they were heard.
    """

    def test_it_reacts_to_the_answer_it_is_given(self):
        brain = FakeBrain("Très bien, donc c'est Hubert qui s'en occupe.")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), brain=brain)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([said("c'est Hubert qui prend", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert suite.remark == "Très bien, donc c'est Hubert qui s'en occupe."
        assert suite.as_is, "une suite déjà formulée ne repasse pas par le modèle"

    def test_the_question_asked_is_given_to_the_model(self):
        """Without it, it would react to an answer whose question it does not know."""
        brain = FakeBrain("…")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), brain=brain)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([said("Hubert", 104.0, 106.0)], now=109.0)
        assert any("Qui porte la migration ?" in c for c in brain.guidance_seen)

    def test_a_nothing_makes_it_go_quiet(self):
        """Two more remarks would make it one participant too many."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                brain=FakeBrain("RIEN"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assert assistant.turn([said("bon, on passe", 104.0, 106.0)],
                              now=109.0) is None

    def test_with_no_brain_it_does_not_go_on(self):
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter())
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        assert assistant.turn([said("Hubert", 104.0, 106.0)], now=109.0) is None

    def test_it_does_not_wait_for_ever(self):
        """Any sentence closes the wait: nothing watches for ever."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                brain=FakeBrain("RIEN"))
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
            brain=FakeBrain("Et qui valide, une fois que c'est fait ?"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([said("Hubert s'en charge", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert assistant.awaiting is suite, "l'échange s'est refermé trop tôt"

    def test_a_conclusion_closes_the_exchange(self):
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            brain=FakeBrain("Très bien, c'est noté."))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([said("Hubert s'en charge", 104.0, 106.0)], now=109.0)
        assert assistant.awaiting is None

    def test_the_rest_does_not_cut_an_exchange_under_way(self):
        """An answer to its own question overrides the rest.

        Otherwise the assistant would ask a question then refuse to hear the answer
        for three minutes, which is worse than asking nothing.
        """
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            brain=FakeBrain("Et pour quand ?"))
        assistant.manners.has_spoken(
            Opening(because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0),
            now=100.0)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        suite = assistant.turn([said("Hubert", 104.0, 106.0)], now=109.0)
        assert suite is not None, "le repos a coupé l'échange"


class TestTheLoopCannotHappen:
    """The cases nobody had thought of, and that a meeting found.

    It speaks through the loudspeaker, and the tool records the system output on
    purpose, which is how it hears the others on a video call. Its voice therefore
    comes back on the others' channel. Each guard below would be enough on its
    own; together they make the cycle impossible, whatever else happens.
    """

    QUESTION = "Lucie, est-ce que tu peux faire des recherches sur Internet ?"

    def _her(self, brain=None, voice=None):
        return AssistantSettings(
            name="Lucie", brain=brain, voice=voice,
            manners=Manners(creux_minimal=0.0),
        )

    def test_with_no_brain_it_keeps_quiet_instead_of_repeating(self):
        """It repeated the question, its own name included, and so called itself."""
        she = self._her()
        rendered = she.answer(
            Opening(because=Because.CALLED, remark=self.QUESTION, born_at=1.0), 2.0
        )
        assert rendered.remark == ""

    def test_what_it_says_never_carries_its_own_name(self):
        class CerveauQuiRepete:
            def write_up(self, _request):
                return "Lucie ne peut pas chercher sur Internet."

        voice = FakeVoiceAdapter()
        she = self._her(brain=CerveauQuiRepete(), voice=voice)
        rendered = she.answer(
            Opening(because=Because.CALLED, remark=self.QUESTION, born_at=1.0), 2.0
        )
        assert "Lucie" not in rendered.remark
        assert voice.remark and "Lucie" not in voice.remark[0]

    def test_it_does_not_react_to_its_own_words(self):
        """The exact case: its sentence comes back through the capture loop."""
        class TheBrain:
            def write_up(self, _request):
                return "Je n'ai pas accès à Internet depuis cette réunion."

        she = self._her(brain=TheBrain(), voice=FakeVoiceAdapter())
        she.answer(
            Opening(because=Because.CALLED, remark=self.QUESTION, born_at=1.0), 2.0
        )
        came_back = [said("Je n'ai pas accès à Internet depuis cette réunion.", 10.0, 14.0)]
        assert she.turn(came_back, 15.0) is None

    def test_a_mangled_transcription_of_its_words_does_not_call_it(self):
        class TheBrain:
            def write_up(self, _request):
                return "Je n'ai pas accès à Internet depuis cette réunion."

        she = self._her(brain=TheBrain(), voice=FakeVoiceAdapter())
        she.answer(
            Opening(because=Because.CALLED, remark=self.QUESTION, born_at=1.0), 2.0
        )
        damaged = [said("je n ai pas acces a internet depuis cette", 10.0, 14.0)]
        assert she.turn(damaged, 15.0) is None

    def test_the_room_is_still_heard(self):
        """The guard must not make it deaf: that is the whole difficulty."""
        class TheBrain:
            def write_up(self, _request):
                return "Je n'ai pas accès à Internet."

        she = self._her(brain=TheBrain(), voice=FakeVoiceAdapter())
        she.answer(
            Opening(because=Because.CALLED, remark=self.QUESTION, born_at=1.0), 2.0
        )
        of_the_room = [said("Lucie, tu peux nous rappeler la date ?", 20.0, 24.0)]
        retained = she.turn(of_the_room, 25.0)
        assert retained is not None and retained.because is Because.CALLED

    def test_it_forgets_its_words_after_a_while(self):
        """Otherwise a participant restating their idea would be taken for it."""
        class TheBrain:
            def write_up(self, _request):
                return "La migration en Symfony sept reste à confier à quelqu'un."

        she = self._her(brain=TheBrain(), voice=FakeVoiceAdapter())
        she.answer(
            Opening(because=Because.CALLED, remark="Lucie, où en est la migration ?",
                    born_at=1.0),
            2.0,
        )
        late = [said("la migration en Symfony sept reste à confier à quelqu'un", 600.0, 606.0)]
        assert she._is_his_own(late[0], 610.0) is False


class TestItMaySearch:
    """It said it could not search the web, with the tools in hand.

    Reported after a meeting. `WebSearch` and `WebFetch` were indeed granted,
    `conversation.recherche_web` being true by default, but the **spoken**
    guidance, which replaces the one for the written conversation, told it to stick
    to what had been said. It obeyed.
    """

    def test_the_spoken_guidance_allows_searching(self):
        from greffier.application.take_part import SPOKEN_GUIDANCE

        guidance_line = SPOKEN_GUIDANCE.format(name="Lucie", nothing=NOTHING)
        assert "chercher en ligne" in guidance_line
        assert "de ton propre chef" in guidance_line

    def test_it_names_the_source_without_saying_the_address(self):
        """A URL cannot be heard; a source with no name cannot be checked."""
        from greffier.application.take_part import SPOKEN_GUIDANCE

        guidance_line = SPOKEN_GUIDANCE.format(name="Lucie", nothing=NOTHING)
        assert "nomme la source à voix haute" in guidance_line
        assert "jamais son" in guidance_line and "adresse" in guidance_line

    def test_it_no_longer_has_to_stick_to_the_meeting(self):
        old = "Si tu n'as pas la réponse dans ce qui a été dit, dis-le"
        from greffier.application.take_part import SPOKEN_GUIDANCE

        assert old not in SPOKEN_GUIDANCE

    def test_the_tools_are_granted_when_the_setting_says_so(self):
        from greffier.adapters.configuration import Config
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.wiring import assistant

        brain = assistant(Config(conversation={"recherche_web": True}))
        assert isinstance(brain, ClaudeWriter)
        assert brain.tools == ClaudeWriter.SEARCH_TOOLS

    def test_the_setting_really_takes_them_away(self):
        """Whoever wants nothing to leave the machine must be able to have that."""
        from greffier.adapters.configuration import Config
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.wiring import assistant

        brain = assistant(Config(conversation={"recherche_web": False}))
        assert isinstance(brain, ClaudeWriter)
        assert brain.tools == ()


class TestStoppedForGood:
    """`stop()` is the end of the meeting, and it must reach a remark in flight.

    Phrasing happens in a separate thread and takes seconds: cutting the
    speaker is not enough, because the thread comes back afterwards and speaks
    into a room where the meeting is over.
    """

    def _her(self, brain=None):
        return AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(), brain=brain or FakeBrain(),
            manners=Manners(active=True),
        )

    def _a_call(self, now=12.0):
        return Opening(because=Because.CALLED, remark="Lucie, une idée ?", born_at=now)

    def test_nothing_is_pronounced_after_a_stop(self):
        she = self._her()
        she.stop()
        assert she.answer(self._a_call(), now=12.0).remark == ""
        assert she.voice.remark == []

    def test_the_speaker_is_cut_by_the_stop(self):
        she = self._her()
        cut_one = []
        she.voice.go_quiet = lambda: cut_one.append(True)
        she.stop()
        assert cut_one == [True]

    def test_a_remark_phrased_during_the_stop_stays_in(self):
        """The thread was already inside the brain when the meeting ended."""
        she = self._her()

        class BrainThatEnds(FakeBrain):
            def write_up(self, text):
                she.stop()
                return super().write_up(text)

        she.brain = BrainThatEnds()
        assert she.answer(self._a_call(), now=12.0).remark == ""
        assert she.voice.remark == []

    def test_a_stop_without_a_voice_does_not_raise(self):
        she = self._her()
        she.voice = None
        she.stop()
        assert she.stopped

    def test_a_speaker_that_fails_to_stop_does_not_raise(self):
        """The neural voice goes through a subprocess: killing it can fail."""
        she = self._her()

        def fall():
            raise OSError("kill: no such process")

        she.voice.go_quiet = fall
        she.stop()
        assert she.stopped

    def test_before_the_stop_she_does_answer(self):
        she = self._her()
        assert she.answer(self._a_call(), now=12.0).remark
        assert she.voice.remark


class TestSheKnowsTheSetting:
    """The glossary of the organisation goes to the assistant, not only to the
    writer of the minutes.

    This room says "CASA", "visa", "OTP" and "recette" for things no general
    model knows, and the writer has been told about them since the beginning
    while the assistant answered on the words alone.
    """

    def _her(self, milieu=None):
        return AssistantSettings(
            name="Lucie", brain=FakeBrain(), manners=Manners(active=True),
            setting=milieu,
        )

    def test_the_glossary_opens_the_guidance(self):
        she = self._her(lambda: "[Contexte] CASA : gestion des logements.\n\n")
        guidance_ = she.guidance()
        assert guidance_.startswith("[Contexte] CASA")
        assert "Lucie" in guidance_, "elle garde ses propres consignes"

    def test_without_a_setting_the_guidance_does_not_change(self):
        assert "Contexte" not in self._her().guidance()

    def test_an_empty_setting_adds_nothing(self):
        assert self._her(lambda: "").guidance() == self._her().guidance()

    def test_a_setting_that_fails_to_read_does_not_silence_her(self):
        """The context file can be missing or unreadable: she still answers."""

        def fall():
            raise OSError("contexte.toml illisible")

        guidance_ = self._her(fall).guidance()
        assert "Lucie" in guidance_ and guidance_

    def test_the_setting_is_read_when_asked_for_and_not_before(self):
        """It is read at each call, so a term added mid-meeting is taken in."""
        calls = []
        she = self._her(lambda: calls.append(1) or "[Contexte] X.\n\n")
        assert not calls
        she.guidance()
        she.guidance()
        assert len(calls) == 2


class TestNothingToAnswerIsSilence:
    """It announced out loud that it had nothing to say. Nine times.

    Read back from the conversation of a real meeting: "Là c'était un échange
    entre vous, pas une question pour moi, je vous laisse continuer", and eight
    more of the same shape. Its name had been picked up in a sentence that was
    not addressed to it, and the guidance told it to say so briefly.

    Saying so is one more intervention: the room hears it, it cuts the meeting,
    and it teaches everybody that the tool is listening in order to judge.
    """

    def _she(self, answer):
        class Brain:
            def __init__(self):
                self.own_guidance = ""

            def write_up(self, text):
                return answer

        return AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                 brain=Brain(), manners=Manners(active=True))

    def _call(self):
        return Opening(because=Because.CALLED, remark="Lucie, une idée ?", born_at=1.0)

    def test_the_word_for_nothing_is_not_pronounced(self):
        she = self._she(NOTHING)
        assert she.answer(self._call(), now=2.0).remark == ""
        assert she.voice.remark == []

    def test_a_sentence_that_starts_with_it_is_not_pronounced_either(self):
        """A model that explains itself says "RIEN, ce n'était pas pour moi"."""
        she = self._she(f"{NOTHING}, ce n'était pas une question pour moi")
        assert she.answer(self._call(), now=2.0).remark == ""

    def test_a_real_answer_still_goes_out(self):
        she = self._she("Le RFC 5545 le permet, avec un TRIGGER négatif.")
        assert she.voice is not None
        assert she.answer(self._call(), now=2.0).remark
        assert she.voice.remark

    def test_the_guidance_names_the_word_that_buys_silence(self):
        from greffier.application.take_part import SPOKEN_GUIDANCE

        guidance_line = SPOKEN_GUIDANCE.format(name="Lucie", nothing=NOTHING)
        assert NOTHING in guidance_line
        assert "pas une question pour moi" in guidance_line, (
            "la consigne nomme la phrase à ne plus dire"
        )

    def test_keeping_quiet_does_not_cost_the_rest(self):
        """It said nothing, so it has not spoken: the rest guards a remark that
        was made, not one that was withheld."""
        she = self._she(NOTHING)
        she.answer(self._call(), now=2.0)
        assert she.manners.spoke_at is None


class TestSpeakingOfHerOwnAccord:
    """With the initiative on, she looks between two slices for something
    worth adding, aside, and the result serves the following slice."""

    def _her(self, response, spoke_at=None, rest=180.0):
        brain = FakeBrain(response)
        her = AssistantSettings(
            name="Lucie", brain=brain, voice=FakeVoiceAdapter(),
            manners=Manners(active=True, creux_minimal=0.0, rest=rest, spoke_at=spoke_at),
            context=lambda: "Jacques : on n'a pas fixé qui relance le partenaire.",
        )
        return her, brain

    def test_a_contribution_comes_with_its_own_guidance(self):
        her, brain = self._her("Personne n'a été désigné pour relancer le partenaire.")
        opening = her.contribution(now=100.0)
        assert opening is not None and opening.because is Because.CONTRIBUTION
        assert "Personne n'a été désigné" in opening.remark
        assert "sans y avoir été invitée à parler" in brain.guidance_seen[0]
        assert brain.own_guidance == "", "the guidance is put back after the call"

    def test_nothing_to_add_is_nothing(self):
        her, _ = self._her(NOTHING)
        assert her.contribution(now=100.0) is None

    def test_she_rests_after_having_spoken(self):
        her, brain = self._her("Encore une idée.", spoke_at=50.0, rest=180.0)
        assert her.contribution(now=100.0) is None
        assert brain.requests == [], "the model is not even asked"

    def test_without_material_the_model_is_not_asked(self):
        her, brain = self._her("Une idée.")
        her.context = lambda: "   "
        assert her.contribution(now=100.0) is None
        assert brain.requests == []

    def test_a_model_that_fails_costs_nothing(self):
        class Broken:
            own_guidance = ""

            def write_up(self, text):
                raise RuntimeError("quota")

        her, _ = self._her("x")
        her.brain = Broken()
        assert her.contribution(now=100.0) is None

    def test_looked_for_aside_the_result_serves_the_next_slice(self):
        her, _ = self._her("Personne n'a été désigné pour relancer le partenaire.")
        her.look_for_a_contribution_aside(now=100.0)
        assert her._search is not None
        her._search.join(timeout=5)
        assert her.in_reserve is not None
        retained = her.turn([said("on passe au point suivant")], now=110.0)
        assert retained is not None and retained.because is Because.CONTRIBUTION
        assert her.in_reserve is None, "handed over once"

    def test_one_search_at_a_time_and_none_while_something_waits(self):
        her, brain = self._her("Une idée.")
        her.in_reserve = Opening(because=Because.CONTRIBUTION, remark="déjà là", born_at=1.0)
        her.look_for_a_contribution_aside(now=100.0)
        assert her._search is None
        assert brain.requests == []


class TestHerTurnIsFiledWhenSheSpeaks:
    """Her turn used to be filed at the moment she was called, three to six
    seconds before a word came out: the chain that runs afterwards looked for
    her voice where there was only the room still talking."""

    def _her(self, clock=None):
        kept = []
        her = AssistantSettings(
            name="Lucie", brain=FakeBrain("Jeudi."), voice=FakeVoiceAdapter(),
            manners=Manners(active=True, creux_minimal=0.0),
            keep_its_turn=lambda start, end: kept.append((start, end)),
            clock=clock,
        )
        return her, kept

    def test_the_turn_starts_at_the_clock_s_time_not_the_call_s(self):
        her, kept = self._her(clock=lambda: 105.5)
        said = her.answer(Opening(because=Because.CALLED, remark="quand ?", born_at=99.0), 100.0)
        assert said.a == 105.5
        assert kept[0][0] == 105.5
        assert her.its_own_turns[0][0] == 105.5
        assert her.manners.spoke_at == 105.5

    def test_without_a_clock_the_call_s_moment_serves(self):
        her, kept = self._her(clock=None)
        her.answer(Opening(because=Because.CALLED, remark="quand ?", born_at=99.0), 100.0)
        assert kept[0][0] == 100.0

    def test_a_clock_behind_the_call_does_not_move_the_turn_back(self):
        her, kept = self._her(clock=lambda: 90.0)
        her.answer(Opening(because=Because.CALLED, remark="quand ?", born_at=99.0), 100.0)
        assert kept[0][0] == 100.0

    def test_a_clock_that_fails_costs_no_answer(self):
        def broken():
            raise OSError("no state file")

        her, kept = self._her(clock=broken)
        said = her.answer(Opening(because=Because.CALLED, remark="quand ?", born_at=99.0), 100.0)
        assert said.remark == "Jeudi."
        assert kept[0][0] == 100.0


class StreamingBrain(FakeBrain):
    """Hands its sentences over one by one before the whole answer, like the session."""

    def __init__(self, response="Oui, je vous entends. La recette est jeudi. Voilà."):
        super().__init__(response)
        self.streamed = []

    def write_up_as_it_comes(self, text, on_sentence):
        self.requests.append(text)
        for sentence in self.response.split(". "):
            sentence = sentence if sentence.endswith((".", "!", "?")) else sentence + "."
            self.streamed.append(sentence)
            on_sentence(sentence)
        return self.response


class MouthOfTheFake:
    def __init__(self, voice):
        self.voice = voice
        self.closed = False

    def add(self, text):
        self.voice.pieces.append(text)

    def close(self):
        self.closed = True
        self.voice.closed += 1


class VoiceThatTakesPieces(FakeVoiceAdapter):
    def __init__(self, works=True, busy=False):
        super().__init__(works)
        self.pieces = []
        self.closed = 0
        self.busy = busy

    def begin(self):
        if self.busy:
            return None
        return MouthOfTheFake(self)


class TestTheAnswerIsSpokenAsItComes:
    """The first sentence reaches the voice while the model writes the rest."""

    def _her(self, **overrides):
        settings = dict(name="Lucie", voice=VoiceThatTakesPieces(), brain=StreamingBrain())
        settings.update(overrides)
        return AssistantSettings(**settings)

    def _called(self):
        return Opening(because=Because.CALLED, remark="tu nous entends ?", born_at=10.0)

    def test_each_sentence_goes_to_the_voice_and_the_mouth_is_closed(self):
        she = self._her()
        rendered = she.answer(self._called(), now=13.0)
        assert she.voice.pieces == ["Oui, je vous entends.", "La recette est jeudi.", "Voilà."]
        assert she.voice.closed == 1
        assert she.voice.remark == [], "the whole remark is not said a second time"
        assert rendered.pronounced and rendered.remark == she.brain.response

    def test_its_own_words_are_kept_before_they_are_spoken(self):
        she = self._her()
        she.answer(self._called(), now=13.0)
        kept = [words for _, words in she.its_own_words]
        assert own_words("La recette est jeudi.") in kept

    def test_its_own_name_never_reaches_the_voice(self):
        she = self._her(brain=StreamingBrain("Lucie a bien entendu. Lucie répond."))
        she.answer(self._called(), now=13.0)
        assert she.voice.pieces and all("Lucie" not in piece for piece in she.voice.pieces)

    def test_a_nothing_opens_no_mouth(self):
        she = self._her(brain=StreamingBrain(f"{NOTHING}. Rien à dire."))
        rendered = she.answer(self._called(), now=13.0)
        assert she.voice.pieces == [] and she.voice.closed == 0
        assert not rendered.pronounced and rendered.remark == ""

    def test_a_busy_voice_keeps_the_remark_for_the_trace(self):
        traces = []
        she = self._her(voice=VoiceThatTakesPieces(busy=True),
                        tracer=lambda who, what: traces.append(what))
        rendered = she.answer(self._called(), now=13.0)
        assert not rendered.pronounced
        assert traces == [she.brain.response]

    def test_a_voice_that_only_takes_a_whole_text_gets_it_at_the_end(self):
        # A speaker with `say` alone: the sentences are gathered for it.
        she = self._her(voice=FakeVoiceAdapter())
        rendered = she.answer(self._called(), now=13.0)
        assert she.voice.remark == [she.brain.response]
        assert rendered.pronounced

    def test_a_brain_that_cannot_stream_is_answered_as_before(self):
        she = self._her(brain=FakeBrain())
        rendered = she.answer(self._called(), now=13.0)
        assert she.voice.remark == ["Oui, je vous entends très bien."]
        assert she.voice.pieces == [] and rendered.pronounced

    def test_a_remark_written_beforehand_does_not_stream(self):
        she = self._her()
        she.answer(Opening(because=Because.CALLED, remark="Merci.", born_at=1.0, as_is=True), 2.0)
        assert she.voice.remark == ["Merci."] and she.voice.pieces == []

    def test_the_moment_it_spoke_is_the_first_sentence_s(self):
        clock = iter([20.0, 25.0, 30.0])
        she = self._her(clock=lambda: next(clock))
        rendered = she.answer(self._called(), now=13.0)
        assert rendered.a == 20.0
        assert she.its_own_turns[0][0] == 20.0


class TestTheWordsJustBeforeTheCall:
    """The thread she answers from runs a slice behind: on the bench she
    answered « ce point n'a pas été mentionné » to a question about the
    sentence said right before it. The pass that hears the call heard those
    words too, and they travel with the question."""

    def test_what_was_heard_before_the_call_travels_with_it(self):
        she = AssistantSettings(name="Lucie")
        retained = she.turn([
            said("On décale donc la recette à jeudi prochain.", 10.0, 13.0),
            said("Lucie, à quel jour est décalée la recette ?", 13.5, 16.0),
        ], now=17.0)
        assert retained is not None
        assert retained.just_before == "On décale donc la recette à jeudi prochain."

    def test_the_words_reach_the_model_with_the_question(self):
        brain = FakeBrain()
        she = AssistantSettings(name="Lucie", brain=brain, context=lambda: "Bonjour.")
        opening = Opening(because=Because.CALLED, remark="à quel jour ?", born_at=1.0,
                          just_before="On décale la recette à jeudi.")
        she.answer(opening, now=2.0)
        assert "On décale la recette à jeudi." in brain.requests[0]
        assert brain.requests[0].index("Bonjour.") < brain.requests[0].index("On décale")
        assert brain.requests[0].index("On décale") < brain.requests[0].index("à quel jour ?")

    def test_a_call_with_nothing_before_it_adds_nothing(self):
        brain = FakeBrain()
        she = AssistantSettings(name="Lucie", brain=brain, context=lambda: "Bonjour.")
        she.answer(Opening(because=Because.CALLED, remark="?", born_at=1.0), now=2.0)
        assert "juste avant" not in brain.requests[0]

    def test_the_words_before_the_name_in_the_same_sentence_are_context(self):
        # The same question, whole, heard by the pass then glued by the slice
        # to the sentence before it: one fingerprint, one answer.
        she = AssistantSettings(name="Lucie")
        first = she.turn([said("Lucie, à quel jour est décalée la recette ?")], now=13.0)
        she.manners.has_spoken(first, 13.5)
        second = she.turn([said(
            "en fin de journée. Lucie, à quel jour est décalée la recette ?", 20.0, 26.0
        )], now=27.0)
        assert second is None, "already answered"

    def test_the_slice_hearing_the_question_in_other_words_does_not_ask_again(self):
        she = AssistantSettings(name="Lucie", brain=FakeBrain())
        first = she.turn([said("Lucie, c'est quoi une pré-production en une phrase ?")], 13.0)
        she.answer(first, now=14.0)
        assert she.turn([said("Lucie, c'est quoi une pré-production ?", 20.0, 23.0)], 24.0) is None
        assert len(she.brain.requests) == 1

    def test_the_same_question_word_for_word_much_later_is_asked_again(self):
        she = AssistantSettings(name="Lucie", brain=FakeBrain(),
                                manners=Manners(creux_minimal=0.0))
        first = she.turn([said("Lucie, à quel jour est décalée la recette ?")], 13.0)
        she.answer(first, now=14.0)
        again = she.turn([said("Lucie, à quel jour est décalée la recette ?", 60.0, 63.0)], 64.0)
        assert again is not None
        she.answer(again, now=65.0)
        assert len(she.brain.requests) == 2

    def test_the_same_question_in_other_words_much_later_is_asked_again(self):
        she = AssistantSettings(name="Lucie", brain=FakeBrain())
        first = she.turn([said("Lucie, c'est quoi une pré-production en une phrase ?")], 13.0)
        she.answer(first, now=14.0)
        again = she.turn([said("Lucie, c'est quoi une pré-production ?", 60.0, 63.0)], 64.0)
        assert again is not None

    def test_her_own_words_are_not_what_was_said_before(self):
        she = AssistantSettings(name="Lucie")
        she.its_own_words.append((9.0, own_words("La recette est décalée à jeudi prochain.")))
        retained = she.turn([
            said("La recette est décalée à jeudi prochain.", 10.0, 13.0),
            said("Lucie, tu confirmes ?", 13.5, 16.0),
        ], now=17.0)
        assert retained is not None and retained.just_before == ""
