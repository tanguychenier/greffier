"""A guided tour of the window, one element lit at a time.

Somebody who has just opened the tool sees six tabs and a blue button.
The tour lights one element after another, on the real window, with a
bubble next to it saying what it is for, and three ways out at every
step, Suivant, Précédent and Quitter, plus Escape. It never blocks a
click on the window behind it, and it never opens a box.

What usually goes wrong with such tours, and what is done about it. A
highlight drawn where the element was before a resize, so the light and
its text sit apart: the light is placed again on every resize. A bubble
placed below an element at the bottom of the window, cut off: the bubble
goes above when there is no room below, and stays inside the window
either way. A tour that cannot be left: Quitter on every bubble, and
Escape. Every stop is photographed by `tools/window_proof.py --tour` and
looked at.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

from greffier.interface.appearance import Button
from greffier.interface.style import Palette, font

#: Thickness of the light around an element, and how far it sits from it.
LIGHT_PX = 3
MARGIN_PX = 6

#: The bubble's width, and the gap between it and the lit element.
BUBBLE_WIDTH = 400
GAP_PX = 14


@dataclass(frozen=True, slots=True)
class Stop:
    """One element of the tour: where it is, and what is said about it."""

    key: str
    target: Callable[[], tk.Misc | None]
    tab: str | None = None
    #: Where the bubble goes first, « below » or « right »; it falls back
    #: to wherever there is room, and always stays inside the window.
    side: str = "below"


class Tour:
    """Walks the window stop by stop; `says` gives the words, `reveal` the tab."""

    def __init__(
        self,
        root: tk.Misc,
        colours: Palette,
        says: Callable[..., str],
        stops: list[Stop],
        reveal: Callable[[str], None],
        on_end: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.colours = colours
        self.says = says
        self.stops = stops
        self.reveal = reveal
        self.on_end = on_end
        self.index = -1
        self._lights: list[tk.Frame] = []
        self._bubble: tk.Frame | None = None
        self._replace_pending = False
        self._showing = False
        self._size: tuple[int, int] | None = None

    @property
    def running(self) -> bool:
        return self.index >= 0

    def start(self) -> None:
        if not self.stops:
            return
        self.root.bind("<Escape>", self._escape, add="+")
        self.root.bind("<Configure>", self._on_resize, add="+")
        self.index = 0
        self._show()

    def next(self) -> None:
        if self.index + 1 >= len(self.stops):
            self.quit()
            return
        self.index += 1
        self._show()

    def back(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._show()

    def quit(self) -> None:
        """Leaves nothing on the window, and says so to whoever asked."""
        self._clear()
        self.index = -1
        with contextlib.suppress(tk.TclError):
            self.root.unbind("<Escape>")
        if self.on_end is not None:
            self.on_end()

    def _escape(self, _event: tk.Event) -> None:
        if self.running:
            self.quit()

    def _on_resize(self, event: tk.Event) -> None:
        """Places the light again once the resize has settled.

        Only when the window itself changed size. Placing the light and the
        bubble raises Configure events too, and a tour that answered them
        placed itself again, which raised them again, without end.
        """
        if not self.running or self._showing or getattr(event, "widget", None) is not self.root:
            return
        size = (self.root.winfo_width(), self.root.winfo_height())
        if size == self._size or self._replace_pending:
            return
        self._replace_pending = True
        self.root.after_idle(self._replace)

    def _replace(self) -> None:
        self._replace_pending = False
        if self.running:
            self._show()

    def _show(self) -> None:
        if self._showing:
            return
        self._showing = True
        try:
            self._clear()
            stop = self.stops[self.index]
            if stop.tab is not None:
                self.reveal(stop.tab)
            self.root.update_idletasks()
            self._size = (self.root.winfo_width(), self.root.winfo_height())
            target = stop.target()
            box = self._box_of(target) if target is not None else None
            if box is not None:
                self._light(box)
            self._speak(stop, box)
        finally:
            self._showing = False

    def _box_of(self, target: tk.Misc) -> tuple[int, int, int, int] | None:
        """The element's rectangle in the root's own coordinates, if it is in view.

        An element scrolled out of the window is mapped as far as Tk knows,
        and a light drawn where it would be lands off the window: nothing is
        lit then, and the bubble sits in the middle.
        """
        with contextlib.suppress(tk.TclError):
            if not target.winfo_ismapped():
                return None
            x = target.winfo_rootx() - self.root.winfo_rootx()
            y = target.winfo_rooty() - self.root.winfo_rooty()
            width, height = target.winfo_width(), target.winfo_height()
            if x < 0 or y < 0 or x + width > self.root.winfo_width() \
                    or y + height > self.root.winfo_height():
                return None
            return x, y, width, height
        return None

    def _light(self, box: tuple[int, int, int, int]) -> None:
        x, y, width, height = box
        left, top = x - MARGIN_PX, y - MARGIN_PX
        right, bottom = x + width + MARGIN_PX, y + height + MARGIN_PX
        for place in (
            (left, top, right - left, LIGHT_PX),
            (left, bottom - LIGHT_PX, right - left, LIGHT_PX),
            (left, top, LIGHT_PX, bottom - top),
            (right - LIGHT_PX, top, LIGHT_PX, bottom - top),
        ):
            frame = tk.Frame(self.root, bg=self.colours.accent, highlightthickness=0)
            frame.place(x=place[0], y=place[1], width=place[2], height=place[3])
            self._lights.append(frame)

    def _speak(self, stop: Stop, box: tuple[int, int, int, int] | None) -> None:
        c = self.colours
        bubble = tk.Frame(self.root, bg=c.board, highlightbackground=c.accent,
                          highlightthickness=2)
        inside = tk.Frame(bubble, bg=c.board)
        inside.pack(padx=16, pady=(12, 12))
        counter = self.says("visite.compteur", n=self.index + 1, total=len(self.stops))
        tk.Label(inside, text=counter, bg=c.board, fg=c.ink_pale, font=font(10),
                 anchor="w").pack(anchor="w")
        tk.Label(inside, text=self.says(f"visite.{stop.key}"), bg=c.board, fg=c.ink,
                 font=font(12), anchor="w", justify="left",
                 wraplength=BUBBLE_WIDTH - 40).pack(anchor="w", pady=(4, 10))
        buttons = tk.Frame(inside, bg=c.board)
        buttons.pack(anchor="w")
        last = self.index + 1 >= len(self.stops)
        Button(buttons, self.says("visite.terminer" if last else "visite.suivant"),
               self.next, c, principal=True, width=104, height=30).pack(side="left")
        if self.index > 0:
            Button(buttons, self.says("visite.precedent"), self.back, c,
                   width=104, height=30).pack(side="left", padx=(8, 0))
        if not last:
            Button(buttons, self.says("visite.quitter"), self.quit, c,
                   width=104, height=30).pack(side="left", padx=(8, 0))
        bubble.update_idletasks()
        x, y = self._bubble_place(box, bubble.winfo_reqheight(), stop.side)
        bubble.place(x=x, y=y, width=BUBBLE_WIDTH)
        self._bubble = bubble

    def _bubble_place(
        self, box: tuple[int, int, int, int] | None, height: int, side: str
    ) -> tuple[int, int]:
        """Next to the lit element where there is room, and inside the window.

        To its right when asked and the window is wide enough, otherwise
        below it, otherwise above it; and whatever the choice, never past
        an edge of the window, since a bubble cut by the edge is a tour that
        cannot be read.
        """
        window_width = max(self.root.winfo_width(), BUBBLE_WIDTH + 2 * GAP_PX)
        window_height = max(self.root.winfo_height(), height + 2 * GAP_PX)
        if box is None:
            return (window_width - BUBBLE_WIDTH) // 2, (window_height - height) // 2
        x, y, box_width, box_height = box
        right = x + box_width + MARGIN_PX + GAP_PX
        if side == "right" and right + BUBBLE_WIDTH <= window_width - GAP_PX:
            return right, self._inside(y - MARGIN_PX, height, window_height)
        left = min(max(GAP_PX, x), window_width - BUBBLE_WIDTH - GAP_PX)
        below = y + box_height + MARGIN_PX + GAP_PX
        if below + height <= window_height - GAP_PX:
            return left, below
        above = y - MARGIN_PX - GAP_PX - height
        return left, self._inside(above, height, window_height)

    @staticmethod
    def _inside(y: int, height: int, window_height: int) -> int:
        return min(max(GAP_PX, y), max(GAP_PX, window_height - height - GAP_PX))

    def _clear(self) -> None:
        for frame in self._lights:
            with contextlib.suppress(tk.TclError):
                frame.destroy()
        self._lights = []
        if self._bubble is not None:
            with contextlib.suppress(tk.TclError):
                self._bubble.destroy()
            self._bubble = None
