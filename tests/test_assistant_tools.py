"""Who is allowed to search, and who never is.

The distinction is the guarantee of the minutes: a document made of what was
said must not be able to complete a decision with what a search engine returned.
"""

from greffier.adapters.brain_claude import ClaudeSession
from greffier.adapters.configuration import Config, Minutes
from greffier.adapters.writer_claude import ClaudeWriter
from greffier.adapters.writer_ollama import OllamaWriter
from greffier.wiring import assistant, writer


def config(assistant=None, minutes_text=None, **conversation) -> Config:
    settings = Config()
    for key, value in conversation.items():
        setattr(settings.conversation, key, value)
    for key, value in (assistant or {}).items():
        setattr(settings.assistant, "model" if key == "modele" else key, value)
    for key, value in (minutes_text or {}).items():
        setattr(settings.minutes, "engine" if key == "moteur" else key, value)
    return settings


class TestTheWriterNeverHasATool:
    def test_no_tool_by_default(self):
        assert ClaudeWriter().tools == ()

    def test_the_writer_of_the_minutes_receives_none(self):
        engine = writer(config())
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()

    def test_even_when_searching_is_switched_on(self):
        """The conversation setting must not leak into the minutes."""
        engine = writer(config(recherche_web=True))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()


class TestTheAssistantMaySearch:
    def test_searching_is_granted_when_it_is_switched_on(self):
        engine = assistant(config(recherche_web=True))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ClaudeWriter.SEARCH_TOOLS

    def test_it_can_be_switched_off_from_the_settings(self):
        """There are meetings where even the term searched for must not leave."""
        engine = assistant(config(recherche_web=False))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()

    def test_the_assistant_does_not_recite_the_plan_of_the_minutes(self):
        """Answering « qui est Maud ? » does not call for Décisions / Actions."""
        engine = assistant(config())
        assert isinstance(engine, ClaudeWriter)
        assert engine.own_guidance
        assert "Décisions" not in engine.own_guidance

    def test_it_is_forbidden_to_send_what_was_said_outside(self):
        engine = assistant(config())
        assert isinstance(engine, ClaudeWriter)
        # Flattened: the guidance spans two lines in the source text.
        flattened = " ".join(engine.own_guidance.split())
        assert "jamais la phrase de la réunion" in flattened

    def test_it_must_give_the_address_of_what_it_finds(self):
        """An answer with no source cannot be checked, and in a meeting one wants to open
        the link straight away.
        """
        flattened = " ".join(assistant(config()).own_guidance.split())
        assert "donne l'adresse" in flattened
        assert "URL complète" in flattened

    def test_it_offers_something_without_inventing_anything(self):
        flattened = " ".join(assistant(config()).own_guidance.split())
        assert "À faire :" in flattened
        assert "N'invente rien pour remplir" in flattened

    def test_it_may_search_of_its_own_accord(self):
        """« Let it do it itself to give itself context », as asked."""
        flattened = " ".join(assistant(config()).own_guidance.split())
        assert "de ton propre chef" in flattened


class TestTheAssistantOfAMeetingKeepsThem:
    """The factory granted the tools; the wiring that runs in a meeting took
    them back on the next line.

    Its guidance says it may look something up and name the source aloud. With
    no tools it answered "oui, je peux chercher sur Internet" and "non, je n'ai
    pas d'accès à Internet ici" in turn, four times in one real meeting.
    """

    def _her(self, **conversation):
        from greffier.wiring import assistant_of

        return assistant_of(config(**conversation), "essai")

    def test_the_meeting_assistant_can_search(self):
        her = self._her(recherche_web=True)
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert her.the_brain.tools == ClaudeSession.SEARCH_TOOLS

    def test_the_setting_still_switches_it_off(self):
        her = self._her(recherche_web=False)
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert her.the_brain.tools == ()

    def test_its_own_guidance_survives_the_change(self):
        her = self._her(recherche_web=True)
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert "Lucie" in her.the_brain.own_guidance or her.name in (
            her.the_brain.own_guidance
        )

    def test_what_it_may_do_matches_what_it_is_told(self):
        """The guidance says it can search; the tools must say the same."""
        her = self._her(recherche_web=True)
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert "chercher en ligne" in her.guidance()
        assert her.the_brain.tools, "dire qu'elle peut chercher sans pouvoir le faire"

    def test_the_search_cue_comes_with_the_tools(self):
        her = self._her(recherche_web=True)
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert her.the_brain.on_search is not None
        assert self._her(recherche_web=False).the_brain.on_search is None


class TestTheMeetingAssistantThinksWithAKeptSession:
    """Called by its name it answered in four seconds, and most of it was a
    process starting. The meeting assistant keeps one open (see `brain_claude`);
    nothing here starts it, that is the meeting's business.
    """

    def _her(self, **settings):
        from greffier.wiring import assistant_of

        return assistant_of(config(**settings), "essai")

    def test_it_is_a_kept_session_and_not_the_writer(self):
        her = self._her()
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert her.the_brain._process is None, "built, not started"

    def test_it_answers_with_the_spoken_model_not_the_writer_s(self):
        her = self._her()
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert her.the_brain.model == "sonnet"
        assert her.the_brain.model != Minutes.CLAUDE_DEFAULT

    def test_the_spoken_model_can_be_chosen(self):
        her = self._her(assistant={"modele": "opus"})
        assert her is not None and isinstance(her.the_brain, ClaudeSession)
        assert her.the_brain.model == "opus"

    def test_with_ollama_the_writer_serves_with_the_spoken_guidance(self):
        her = self._her(minutes_text={"moteur": "ollama"})
        assert her is not None and isinstance(her.the_brain, OllamaWriter)
        assert "prononcé tel" in her.the_brain.own_guidance
