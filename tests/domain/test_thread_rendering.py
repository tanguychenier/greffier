"""Le fil du direct, rendu en texte pour qu'on puisse l'interroger."""

from greffier.domain.live import LiveThread, LiveTurn
from greffier.domain.models import Span


def thread_with(*turns: tuple[int, float, float, str, str]) -> LiveThread:
    thread = LiveThread()
    for number, start, end, text, voice in turns:
        thread.turns.append(LiveTurn(number, Span(start, end), text, voice))
    return thread


class TestRenderingTheThread:
    """Avant, la conversation exigeait un compte rendu, donc une réunion finie.

    Impossible de demander « qu'a-t-on décidé sur Oasis ? » pendant qu'on en
    parle, alors que le fil était déjà là.
    """

    def test_the_text_is_timestamped_and_attributed(self):
        rendered = thread_with((1, 0.0, 5.0, "Bonjour à tous.", "v1")).rendered()
        assert "00:00" in rendered
        assert "Bonjour à tous." in rendered

    def test_the_turns_of_one_voice_are_grouped(self):
        """Une étiquette par phrase rend le texte illisible pour qui le résume."""
        rendered = thread_with(
            (1, 0.0, 5.0, "Première phrase.", "v1"),
            (2, 5.0, 9.0, "Seconde phrase.", "v1"),
        ).rendered()
        etiquettes = [line for line in rendered.splitlines() if line.startswith("[")]
        assert len(etiquettes) == 1

    def test_a_change_of_voice_opens_a_block(self):
        rendered = thread_with(
            (1, 0.0, 5.0, "Moi d'abord.", "v1"),
            (2, 5.0, 9.0, "Moi ensuite.", "v2"),
        ).rendered()
        assert len([line for line in rendered.splitlines() if line.startswith("[")]) == 2

    def test_an_empty_thread_renders_nothing(self):
        assert LiveThread().rendered() == ""

    def test_turns_with_no_text_are_dropped(self):
        assert thread_with((1, 0.0, 5.0, "   ", "v1")).rendered() == ""

    def test_only_the_end_can_be_asked_for(self):
        """Une longue réunion n'a pas à repartir en entier à chaque question."""
        rendered = thread_with(
            (1, 0.0, 10.0, "Le début, très ancien.", "v1"),
            (2, 600.0, 610.0, "La fin, celle qui compte.", "v1"),
        ).rendered(since=300.0)
        assert "celle qui compte" in rendered
        assert "très ancien" not in rendered

    def test_the_timestamp_passes_the_minute(self):
        rendered = thread_with((1, 125.0, 130.0, "Deux minutes cinq.", "v1")).rendered()
        assert "02:05" in rendered
