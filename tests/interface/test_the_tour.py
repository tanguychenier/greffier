"""The guided tour, on the real window.

What such tours get wrong, and what is checked here on the painted window:
the light drawn beside its text, a bubble cut by the edge, a tour that
cannot be left. The images are looked at through `tools/window_proof.py
--tour`; the tests hold what the images showed.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from greffier.interface.window import TOUR_TAKEN


def _inside(window, widget: tk.Misc) -> bool:
    root = window.root
    x = widget.winfo_rootx() - root.winfo_rootx()
    y = widget.winfo_rooty() - root.winfo_rooty()
    return (x >= 0 and y >= 0 and x + widget.winfo_width() <= root.winfo_width()
            and y + widget.winfo_height() <= root.winfo_height())


def _placed(window) -> list[tk.Misc]:
    """The widgets the tour placed on the root: the lights and the bubble."""
    return [w for w in window.root.winfo_children() if w.winfo_manager() == "place"]


class TestTheTourWalksTheWindow:
    def test_every_stop_has_its_words_in_the_catalogue(self, window) -> None:
        tour = window.the_tour()
        assert len(tour.stops) == 10
        for stop in tour.stops:
            assert window.says(f"visite.{stop.key}") != f"visite.{stop.key}"

    def test_the_light_frames_the_element_and_the_bubble_stays_in_the_window(
        self, window
    ) -> None:
        window.root.geometry("1280x760")
        window.root.update()
        tour = window.the_tour()
        tour.start()
        for rank in range(len(tour.stops)):
            window.root.update()
            placed = _placed(window)
            assert len(placed) == 5, f"stop {rank + 1}: four lights and a bubble"
            assert all(_inside(window, w) for w in placed), f"stop {rank + 1} spills out"
            lights = placed[:4]
            target = tour.stops[rank].target()
            assert target is not None
            left = min(w.winfo_rootx() for w in lights)
            top = min(w.winfo_rooty() for w in lights)
            assert left < target.winfo_rootx() <= left + 10
            assert top < target.winfo_rooty() <= top + 10
            tour.next()
        assert not tour.running
        assert _placed(window) == []

    def test_the_last_stop_ends_the_tour_and_writes_the_marker(self, window) -> None:
        tour = window.the_tour()
        tour.start()
        for _ in range(len(tour.stops)):
            tour.next()
        assert not tour.running
        assert (window.config.paths.data / TOUR_TAKEN).exists()

    def test_escape_leaves_the_tour_at_any_stop(self, window) -> None:
        tour = window.the_tour()
        tour.start()
        tour.next()
        window.root.update()
        window.root.event_generate("<Escape>")
        window.root.update()
        assert not tour.running and _placed(window) == []
        assert (window.config.paths.data / TOUR_TAKEN).exists()

    def test_back_goes_to_the_previous_stop(self, window) -> None:
        tour = window.the_tour()
        tour.start()
        tour.next()
        tour.next()
        tour.back()
        assert tour.index == 1
        tour.quit()

    def test_the_light_follows_the_element_when_the_window_is_resized(self, window) -> None:
        window.root.geometry("900x700")
        window.root.update()
        tour = window.the_tour()
        tour.start()
        tour.next()  # the start button, whose place moves with the window
        window.root.update()
        window.root.geometry("1280x760")
        window.root.update()
        window.root.update()
        lights = _placed(window)[:4]
        target = tour.stops[1].target()
        assert target is not None
        assert min(w.winfo_rootx() for w in lights) < target.winfo_rootx()
        assert max(w.winfo_rootx() + w.winfo_width() for w in lights) > (
            target.winfo_rootx() + target.winfo_width())
        tour.quit()

    def test_a_second_start_does_not_double_the_tour(self, window) -> None:
        window.start_the_tour()
        window.start_the_tour()
        window.root.update()
        assert len(_placed(window)) == 5
        window._tour.quit()


class TestTheTourOpensItselfOnce:
    def test_not_on_a_test_screen(self, window) -> None:
        # The proofs and the tests drive the window themselves.
        window._offer_the_tour()
        assert getattr(window, "_tour", None) is None

    def test_once_taken_it_does_not_come_back(self, window, monkeypatch) -> None:
        monkeypatch.delenv("GREFFIER_ECRAN_D_ESSAI", raising=False)
        window._tour_taken()
        window._offer_the_tour()
        assert getattr(window, "_tour", None) is None

    def test_on_a_fresh_machine_it_opens(self, window, monkeypatch) -> None:
        monkeypatch.delenv("GREFFIER_ECRAN_D_ESSAI", raising=False)
        window._offer_the_tour()
        assert window._tour.running
        window._tour.quit()

    @pytest.mark.usefixtures("window")
    def test_the_settings_offer_the_tour_again(self, window) -> None:
        assert window.tour_button.winfo_exists()
