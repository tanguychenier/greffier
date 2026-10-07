"""The live thread, rendered as text so that it can be queried."""

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.live import LiveThread, LiveTurn
from greffier.domain.models import Span


def thread_with(*turns: tuple[int, float, float, str, str]) -> LiveThread:
    thread = LiveThread()
    for number, start, end, text, voice in turns:
        thread.turns.append(LiveTurn(number, Span(start, end), text, voice))
    return thread


class TestRenderingTheThread:
    """Before, the conversation required minutes, hence a finished meeting.

    Impossible to ask « qu'a-t-on décidé sur Oasis ? » while it is being
    discussed, though the thread was already there.
    """

    def test_the_text_is_timestamped_and_attributed(self):
        rendered = thread_with((1, 0.0, 5.0, "Bonjour à tous.", "v1")).rendered()
        assert "00:00" in rendered
        assert "Bonjour à tous." in rendered

    def test_the_turns_of_one_voice_are_grouped(self):
        """One label per sentence makes the text unreadable for whoever summarises it."""
        rendered = thread_with(
            (1, 0.0, 5.0, "Première phrase.", "v1"),
            (2, 5.0, 9.0, "Seconde phrase.", "v1"),
        ).rendered()
        labels = [line for line in rendered.splitlines() if line.startswith("[")]
        assert len(labels) == 1

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
        """A long meeting does not have to be sent whole at every question."""
        rendered = thread_with(
            (1, 0.0, 10.0, "Le début, très ancien.", "v1"),
            (2, 600.0, 610.0, "La fin, celle qui compte.", "v1"),
        ).rendered(since=300.0)
        assert "celle qui compte" in rendered
        assert "très ancien" not in rendered

    def test_the_timestamp_passes_the_minute(self):
        rendered = thread_with((1, 125.0, 130.0, "Deux minutes cinq.", "v1")).rendered()
        assert "02:05" in rendered

    def test_the_first_second_of_the_meeting_is_shown_as_well(self):
        assert "Oui." in thread_with((1, 0.0, 0.5, "Oui.", "v1")).rendered()

    def test_a_turn_ending_on_the_instant_asked_for_is_still_shown(self):
        rendered = thread_with((1, 0.0, 10.0, "Jusqu'ici.", "v1")).rendered(since=10.0)
        assert "Jusqu'ici." in rendered

    def test_the_text_reads_as_a_script(self):
        """One label per block, one timestamped line per sentence, a blank line
        between two speakers: what the writer is handed."""
        rendered = thread_with(
            (1, 0.0, 5.0, "Bonjour à tous.", "v1"),
            (2, 5.0, 9.0, "On commence.", "v1"),
            (3, 9.0, 12.0, "Allons-y.", "v2"),
        ).rendered()
        assert rendered == (
            "[Voix v1]\n00:00  Bonjour à tous.\n00:05  On commence.\n\n[Voix v2]\n00:09  Allons-y."
        )

    @given(st.lists(
        st.tuples(st.sampled_from(["v1", "v2", "v3"]),
                  st.sampled_from(["", "  ", "Oui.", "Non.", "Peut-être."])),
        max_size=10,
    ))
    def test_one_label_per_run_of_the_same_voice(self, said):
        """Whatever is said, the labels count the changes of voice among the
        sentences that have words, and the words come out in order."""
        thread = LiveThread()
        for number, (voice, text) in enumerate(said, start=1):
            thread.turns.append(LiveTurn(number, Span(float(number), number + 1.0), text, voice))
        spoken = [(voice, text) for voice, text in said if text.strip()]
        runs = sum(
            1 for i, (voice, _) in enumerate(spoken) if i == 0 or voice != spoken[i - 1][0]
        )
        lines = thread.rendered().splitlines()
        assert sum(1 for line in lines if line.startswith("[")) == runs
        assert [line.split("  ", 1)[1] for line in lines if line and not line.startswith("[")] == [
            text for _, text in spoken
        ]
