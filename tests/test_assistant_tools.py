"""Who is allowed to search, and who never is.

The distinction is the guarantee of the minutes: a document made of what was
said must not be able to complete a decision with what a search engine returned.
"""

from greffier.adapters.configuration import Config
from greffier.adapters.writer_claude import ClaudeWriter
from greffier.wiring import assistant, writer


def config(**conversation) -> Config:
    settings = Config()
    for key, value in conversation.items():
        setattr(settings.conversation, key, value)
    return settings


class TestTheWriterNeverHasATool:
    def test_aucun_outil_par_defaut(self):
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


class TestLAssistantPeutChercher:
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
        """Répondre « qui est Maud ? » n'appelle pas Décisions / Actions."""
        engine = assistant(config())
        assert isinstance(engine, ClaudeWriter)
        assert engine.consignes_propres
        assert "Décisions" not in engine.consignes_propres

    def test_it_is_forbidden_to_send_what_was_said_outside(self):
        engine = assistant(config())
        assert isinstance(engine, ClaudeWriter)
        # Flattened: the guidance spans two lines in the source text.
        aplati = " ".join(engine.consignes_propres.split())
        assert "jamais la phrase de la réunion" in aplati

    def test_it_must_give_the_address_of_what_it_finds(self):
        """An answer with no source cannot be checked, and in a meeting one wants to open
        the link straight away.
        """
        aplati = " ".join(assistant(config()).consignes_propres.split())
        assert "donne l'adresse" in aplati
        assert "URL complète" in aplati

    def test_it_offers_something_without_inventing_anything(self):
        aplati = " ".join(assistant(config()).consignes_propres.split())
        assert "À faire :" in aplati
        assert "N'invente rien pour remplir" in aplati

    def test_it_may_search_of_its_own_accord(self):
        """« Qu'il le fasse lui-même pour se donner du contexte » — demandé."""
        aplati = " ".join(assistant(config()).consignes_propres.split())
        assert "de ton propre chef" in aplati


class TestTheAssistantOfAMeetingKeepsThem:
    """The factory granted the tools; the wiring that runs in a meeting took
    them back on the next line.

    Its guidance says it may look something up and name the source aloud. With
    no tools it answered "oui, je peux chercher sur Internet" and "non, je n'ai
    pas d'accès à Internet ici" in turn, four times in one real meeting.
    """

    def _lui(self, **conversation):
        from greffier.wiring import assistant_of

        return assistant_of(config(**conversation), "essai")

    def test_the_meeting_assistant_can_search(self):
        lui = self._lui(recherche_web=True)
        assert lui is not None and isinstance(lui.cerveau, ClaudeWriter)
        assert lui.cerveau.tools == ClaudeWriter.SEARCH_TOOLS

    def test_the_setting_still_switches_it_off(self):
        lui = self._lui(recherche_web=False)
        assert lui is not None and isinstance(lui.cerveau, ClaudeWriter)
        assert lui.cerveau.tools == ()

    def test_its_own_guidance_survives_the_change(self):
        lui = self._lui(recherche_web=True)
        assert lui is not None and isinstance(lui.cerveau, ClaudeWriter)
        assert "Lucie" in lui.cerveau.consignes_propres or lui.name in (
            lui.cerveau.consignes_propres
        )

    def test_what_it_may_do_matches_what_it_is_told(self):
        """The guidance says it can search; the tools must say the same."""
        lui = self._lui(recherche_web=True)
        assert lui is not None and isinstance(lui.cerveau, ClaudeWriter)
        assert "chercher en ligne" in lui.guidance()
        assert lui.cerveau.tools, "dire qu'elle peut chercher sans pouvoir le faire"
