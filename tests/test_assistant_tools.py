"""Qui a le droit de chercher, et qui ne l'a jamais.

La distinction est la garantie du compte rendu : un document qui se compose de
ce qui a été dit ne doit pas pouvoir compléter une décision par ce qu'un moteur
de recherche a rendu.
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
        """Le réglage de la conversation ne doit pas fuir vers le compte rendu."""
        engine = writer(config(recherche_web=True))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()


class TestLAssistantPeutChercher:
    def test_searching_is_granted_when_it_is_switched_on(self):
        engine = assistant(config(recherche_web=True))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ClaudeWriter.SEARCH_TOOLS

    def test_it_can_be_switched_off_from_the_settings(self):
        """Il y a des réunions où même le terme cherché ne doit pas sortir."""
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
        # Aplati : la consigne tient sur deux lignes dans le texte source.
        aplati = " ".join(engine.consignes_propres.split())
        assert "jamais la phrase de la réunion" in aplati

    def test_it_must_give_the_address_of_what_it_finds(self):
        """Une réponse sans sa source ne se vérifie pas, et en réunion on veut
        pouvoir ouvrir le lien tout de suite."""
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
