"""The real window, built and painted, rather than what it computes.

`test_window.py` covers what the window works out before showing anything. It
cannot see what these tests see: that the window opens at all, that it opens
**before** it asks anything, and that every tab paints. The fixture for this
existed and no test used it, which is how a modal box came to be opened from
`__init__` -- on a machine with no models, the first thing Greffier did was ask
for a gigabyte and a half over an empty grey rectangle, and the proof of the
window hung there instead of photographing it.
"""

from __future__ import annotations

import pytest

from greffier.interface import asking

TABS = ("Préparation", "Réunions", "En direct", "Voix", "Conversation", "Réglages")


class TestOpeningBeforeAsking:
    def test_building_the_window_asks_nothing(self, test_screen) -> None:
        # The question about the missing models is owed -- this machine has
        # none -- and it is owed *after* there is a window behind it.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        built = Window(Config())
        try:
            assert asking.unanswered() == []
            assert built.root.winfo_exists()
        finally:
            built.root.destroy()

    def test_the_question_comes_once_the_window_is_painted(self, test_screen) -> None:
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        built = Window(Config())
        try:
            built.root.update()
            asked = asking.unanswered()
            assert asked, "la proposition des modèles n'est jamais venue"
            assert any("Go" in question or "modèle" in question for question in asked)
        finally:
            built.root.destroy()

    def test_nothing_is_fetched_when_nobody_answered(self, test_screen) -> None:
        # No answer means no: a gigabyte and a half is not something to start
        # on a machine where nobody said yes.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        built = Window(Config())
        try:
            built.root.update()
            assert built.travaux == []
        finally:
            built.root.destroy()


class TestEveryTabPaints:
    def test_the_six_tabs_are_there(self, window) -> None:
        assert tuple(window.tabs._pages) == TABS

    @pytest.mark.parametrize("caption", TABS)
    def test_a_tab_paints_and_holds_something(self, window, caption: str) -> None:
        window.tabs.reveal(caption)
        window.root.update()
        page = window.tabs._pages[caption]
        assert page.winfo_children(), f"l'onglet « {caption} » est vide"

    def test_switching_tabs_does_not_resize_the_window(self, window) -> None:
        # The window changed size on every tab switch until `geometry()` was
        # set once and for all; nothing must bring that back.
        window.root.update()
        width, height = window.root.winfo_width(), window.root.winfo_height()
        for caption in TABS:
            window.tabs.reveal(caption)
            window.root.update()
        assert (window.root.winfo_width(), window.root.winfo_height()) == (width, height)


class TestWhatTheWindowShowsWithNothingYet:
    def test_it_says_it_is_ready_rather_than_nothing(self, window) -> None:
        window.root.update()
        assert "Prêt" in window.title.cget("text")

    def test_the_status_line_starts_empty(self, window) -> None:
        assert window.status_line.cget("text") == ""
