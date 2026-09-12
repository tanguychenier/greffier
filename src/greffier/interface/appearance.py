"""The window's drawn widgets.

Drawn rather than native: Tk's own widgets cannot be styled far enough, and a
tool that goes on television has to look like it was made on purpose.
"""

from __future__ import annotations

import contextlib
import functools
import tkinter as tk
from collections.abc import Callable

from greffier.interface.readable import button_grid, dot_marker
from greffier.interface.style import Palette, font

MAIN = "hand2"

def rounded_rectangle(
    toile: tk.Canvas,
    x1: float, y1: float, x2: float, y2: float,
    rayon: float,
    fill: str = "",
    outline: str = "",
) -> int:
    """A rounded rectangle, which Tk does not provide."""
    return toile.create_polygon(
        _rounded_points(x1, y1, x2, y2, rayon),
        smooth=True, splinesteps=24, fill=fill, outline=outline,
    )

class Button(tk.Canvas):
    """A drawn button: rounded corners, hover, and a hand cursor."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        action: Callable[[], None],
        colours: Palette,
        principal: bool = False,
        width: int = 210,
        height: int = 38,
    ) -> None:
        ground = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else colours.ground
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=ground)
        self.colours = colours
        self.principal = principal
        self.action = action
        self._active = True
        self._forme = rounded_rectangle(
            self, 1, 1, width - 1, height - 1, 9,
            fill=self._plain_background(), outline=colours.rule if not principal else "",
        )
        self._text = self.create_text(
            width / 2, height / 2, text=text,
            fill=self._ink(), font=font(12, principal),
        )
        self._height = height
        self._rayon = 9
        self.bind("<Enter>", lambda _e: self._paint(hover=True))
        self.bind("<Leave>", lambda _e: self._paint(hover=False))
        self.bind("<Button-1>", lambda _e: self.action() if self._active else None)

    def redimensionner(self, width: int) -> None:
        """Takes the button's width again, shape and text together."""
        width = max(48, int(width))
        if width == int(self.cget("width")):
            return
        self.configure(width=width)
        self.delete(self._forme)
        self._forme = rounded_rectangle(
            self, 1, 1, width - 1, self._height - 1, self._rayon,
            fill=self._plain_background(),
            outline=self.colours.rule if not self.principal else "",
        )
        self.tag_lower(self._forme, self._text)
        self.coords(self._text, width / 2, self._height / 2)

    def _plain_background(self) -> str:
        return self.colours.accent if self.principal else self.colours.board

    def _ink(self) -> str:
        if not self._active:
            return self.colours.calm
        return self.colours.accent_ink if self.principal else self.colours.ink

    def _paint(self, hover: bool) -> None:
        if not self._active:
            return
        if self.principal:
            self.itemconfigure(self._forme, fill=self.colours.accent)
        else:
            self.itemconfigure(
                self._forme, fill=self.colours.hover if hover else self.colours.board
            )
        self.configure(cursor=MAIN if hover else "")

    def _en_avant(self) -> Button:
        """The action of a screen, without competing with the one of the window.

        One filled button per view: « Démarrer la réunion » is what the tool is
        for and keeps it. The action of a tab is marked by its outline and its
        ink, which the eye finds second rather than first.
        """
        self.itemconfigure(self._forme, outline=self.colours.accent)
        self.itemconfigure(self._text, fill=self.colours.accent)
        return self

    def _efface(self) -> Button:
        """Irreversible, so quiet: pale text, no border, alone at the far end.

        « Supprimer » sat in a row of eight identical buttons, beside
        « Traiter ». What cannot be undone must not look like what can.
        """
        self.itemconfigure(self._forme, outline="", fill=self.colours.board)
        self.itemconfigure(self._text, fill=self.colours.calm)
        return self

    def hold(self, press: Callable[[], None], release: Callable[[], None]) -> Button:
        """Acts while it is held down rather than when it is clicked.

        For speaking to the assistant: pressing opens the microphone, releasing
        closes it. A microphone that opens on a click and closes on another is a
        microphone somebody leaves open.
        """
        self.unbind("<Button-1>")
        self.bind("<ButtonPress-1>", lambda _e: press() if self._active else None)
        self.bind("<ButtonRelease-1>", lambda _e: release() if self._active else None)
        return self

    def set_caption(self, text: str) -> None:
        self.itemconfigure(self._text, text=text)

    def highlight(self, principal: bool) -> None:
        """Switches between the look of a main action and the ordinary one.

        A button that changes state has to show it: « Lucie participe » hollow and
        « Faire taire Lucie » filled are not mistaken for one another at a glance,
        which a label alone does not guarantee in the middle of a meeting.
        """
        if principal == self.principal:
            return
        self.principal = principal
        self.itemconfigure(self._forme, fill=self._plain_background(),
                           outline="" if principal else self.colours.rule)
        self.itemconfigure(self._text, fill=self._ink(),
                           font=font(12, principal))

    def activer(self, yes: bool) -> None:
        self._active = yes
        self.itemconfigure(self._text, fill=self._ink())
        self.itemconfigure(
            self._forme,
            fill=self._plain_background() if yes else self.colours.hover,
        )

class Listing(tk.Canvas):
    """A drawn dropdown, in place of Tk's own."""

    def __init__(
        self,
        parent: tk.Misc,
        colours: Palette,
        width: int = 320,
        height: int = 32,
        on_choice: Callable[[str], None] | None = None,
    ) -> None:
        ground = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else colours.board
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=ground)
        self.colours = colours
        self.width = width
        self.height = height
        self.on_choice = on_choice
        self._choix: list[tuple[str, str]] = []
        self._key = ""
        self._active = True
        self._forme = rounded_rectangle(
            self, 1, 1, width - 1, height - 1, 8,
            fill=colours.ground, outline=colours.rule,
        )
        self._text = self.create_text(
            12, height / 2, text="", anchor="w", fill=colours.ink, font=font(12),
        )
        pointe = width - 15
        milieu = height / 2
        self._chevron = self.create_line(
            [pointe - 5, milieu - 2, pointe, milieu + 3, pointe + 5, milieu - 2],
            fill=colours.ink_pale, width=1.6, capstyle="round", joinstyle="round",
        )
        self.bind("<Enter>", lambda _e: self._paint(hover=True))
        self.bind("<Leave>", lambda _e: self._paint(hover=False))
        self.bind("<Button-1>", self._deployer)
        # Faire défiler la page pendant qu'une liste est ouverte la laissait
        # flotter au-dessus d'un réglage qui avait bougé. La molette la range.
        self.bind_all("<MouseWheel>", self._ranger, add="+")
        self.bind_all("<Button-4>", self._ranger, add="+")
        self.bind_all("<Button-5>", self._ranger, add="+")

    def fill_menu(self, choix: list[tuple[str, str]], key: str = "") -> None:
        """Places the possible choices, and selects one."""
        self._choix = list(choix)
        known = [c for c, _ in self._choix]
        self._key = key if key in known else (known[0] if known else "")
        self._show()

    def value(self) -> str:
        return self._key

    def choose(self, key: str) -> None:
        if key != self._key and key in [c for c, _ in self._choix]:
            self._key = key
            self._show()

    def activer(self, yes: bool) -> None:
        self._active = yes
        self.itemconfigure(self._text,
                           fill=self.colours.ink if yes else self.colours.calm)
        self.itemconfigure(self._chevron,
                           fill=self.colours.ink_pale if yes else self.colours.calm)

    def _label_text(self) -> str:
        for key, label_text in self._choix:
            if key == self._key:
                return label_text
        return ""

    def _show(self) -> None:
        place = self.width - 34
        label_text = self._label_text()
        while label_text and self._text_width(label_text) > place:
            label_text = label_text[:-2] + "…"
        self.itemconfigure(self._text, text=label_text)

    def _text_width(self, text: str) -> int:
        essai = self.create_text(-1000, -1000, text=text, anchor="w", font=font(12))
        left, _, right, _ = self.bbox(essai)
        self.delete(essai)
        return int(right - left)

    def _paint(self, hover: bool) -> None:
        if not self._active:
            return
        self.itemconfigure(
            self._forme,
            fill=self.colours.hover if hover else self.colours.ground,
            outline=self.colours.ink_pale if hover else self.colours.rule,
        )
        self.configure(cursor=MAIN if hover else "")

    def _deployer(self, _event: tk.Event | None = None) -> None:
        if not self._active or not self._choix:
            return
        c = self.colours
        self._ranger()
        menu = tk.Menu(self, tearoff=0, font=font(12), bg=c.board, fg=c.ink,
                       activebackground=c.hover, activeforeground=c.ink,
                       borderwidth=0, relief="flat", activeborderwidth=0)
        for key, label_text in self._choix:
            marque = "✓ " if key == self._key else "   "
            menu.add_command(label=f"{marque}{label_text}",
                             command=functools.partial(self._retenir, key))
        self._menu: tk.Menu | None = menu
        # `tk_popup` et non `post` : le premier prend la main, donc un clic
        # ailleurs referme la liste. Avec `post`, rien ne la refermait -- elle
        # restait affichée pendant qu'on faisait défiler la page derrière, et
        # une liste posée sur un réglage qu'elle ne désigne plus est pire
        # qu'une liste fermée.
        try:
            menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.height)
        finally:
            menu.grab_release()

    def _ranger(self, _event: tk.Event | None = None) -> None:
        """Closes the list and forgets it. Menus are not free to keep."""
        menu = getattr(self, "_menu", None)
        if menu is None:
            return
        self._menu = None
        with contextlib.suppress(tk.TclError):
            menu.unpost()
            menu.destroy()

    def _retenir(self, key: str) -> None:
        change = key != self._key
        self._key = key
        self._show()
        if change and self.on_choice is not None:
            self.on_choice(key)

class Scroller(tk.Canvas):
    """A thin drawn scrollbar, in place of Tk's own."""

    def __init__(
        self, parent: tk.Misc, colours: Palette,
        command: Callable[..., None], width: int = 8,
    ) -> None:
        ground = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else colours.board
        super().__init__(parent, width=width, highlightthickness=0, bg=ground)
        self.colours = colours
        self.command = command
        self.width = width
        self._premier = 0.0
        self._dernier = 1.0
        self._pouce = rounded_rectangle(self, 1, 0, width - 1, 0, width / 2)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._move)
        self.bind("<B1-Motion>", self._move)
        self.bind("<Enter>", lambda _e: self._tint(hover=True))
        self.bind("<Leave>", lambda _e: self._tint(hover=False))
        self._tint(hover=False)

    def set(self, premier: str | float, dernier: str | float) -> None:
        """Called by the followed widget through yscrollcommand."""
        self._premier, self._dernier = float(premier), float(dernier)
        self._draw()

    def _tint(self, hover: bool) -> None:
        self.itemconfigure(
            self._pouce, fill=self.colours.ink_pale if hover else self.colours.calm
        )

    def _draw(self) -> None:
        height = self.winfo_height()
        if height <= 1 or self._dernier - self._premier >= 0.999:
            self.itemconfigure(self._pouce, state="hidden")
            return
        self.itemconfigure(self._pouce, state="normal")
        minimum = min(24, height)
        haut = self._premier * height
        bas = max(self._dernier * height, haut + minimum)
        self.coords(
            self._pouce, *_rounded_points(1, haut, self.width - 1, bas, self.width / 2)
        )

    def _move(self, event: tk.Event) -> None:
        height = self.winfo_height() or 1
        portee = self._dernier - self._premier
        target = event.y / height - portee / 2
        self.command("moveto", max(0.0, min(1.0 - portee, target)))

class LevelMeter(tk.Canvas):
    """A rounded level bar that changes colour with the level."""

    def __init__(
        self, parent: tk.Misc, colours: Palette, width: int = 300, height: int = 8
    ) -> None:
        ground = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else colours.board
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=ground)
        self.colours = colours
        self.width = width
        self.height = height
        rounded_rectangle(self, 0, 0, width, height, height / 2,
                          fill=colours.rule, outline="")
        self._jauge = rounded_rectangle(self, 0, 0, 1, height, height / 2,
                                        fill=colours.green, outline="")
        self._value = 0.0
        self._target = 0.0
        self._glisse: str | None = None

    def reveal(self, part: float) -> None:
        self._target = max(0.0, min(1.0, part))
        if self._glisse is None:
            self._step()

    def _step(self) -> None:
        if not self.winfo_exists():
            self._glisse = None
            return
        gap = self._target - self._value
        if abs(gap) < 0.004:
            self._value = self._target
            self._draw()
            self._glisse = None
            return
        self._value += gap * 0.32
        self._draw()
        self._glisse = self.after(30, self._step)

    def _draw(self) -> None:
        part = self._value
        if part <= 0.01:
            self.itemconfigure(self._jauge, state="hidden")
            return
        self.itemconfigure(self._jauge, state="normal")
        length = max(self.height, part * self.width)
        self.coords(self._jauge, *_rounded_points(0, 0, length, self.height,
                                                   self.height / 2))
        self.itemconfigure(
            self._jauge, fill=self.colours.amber if part > 0.7 else self.colours.green
        )

def _rounded_points(
    x1: float, y1: float, x2: float, y2: float, rayon: float
) -> list[float]:
    rayon = min(rayon, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    return [
        x1 + rayon, y1, x2 - rayon, y1, x2, y1, x2, y1 + rayon,
        x2, y2 - rayon, x2, y2, x2 - rayon, y2, x1 + rayon, y2,
        x1, y2, x1, y2 - rayon, x1, y1 + rayon, x1, y1,
    ]

class _Segment(tk.Canvas):
    """A drawn tab, which knows how to paint itself selected."""

    PLACE_PASTILLE = 26

    def __init__(self, parent: tk.Misc, caption: str, colours: Palette,
                 action: Callable[[str], None]) -> None:
        self.largeur_nue = len(caption) * 9 + 34
        super().__init__(parent, width=self.largeur_nue, height=32,
                         highlightthickness=0, bg=colours.ground)
        self.caption = caption
        self.colours = colours
        self._count = 0
        self._choisi = False
        self.forme = -1
        self.text = -1
        self._draw()
        self.bind("<Button-1>", lambda _e: action(self.caption))
        self.bind("<Enter>", lambda _e: self.configure(cursor=MAIN))
        self.bind("<Leave>", lambda _e: self.configure(cursor=""))

    def _draw(self) -> None:
        """Draws it all again: the width changes with the badge.

        Redrawing rather than moving, because the rounded shape is made of segments
        whose width cannot change without remaking them.
        """
        self.delete("all")
        width = self.largeur_nue + (self.PLACE_PASTILLE if self._count else 0)
        self.configure(width=width)
        self.forme = rounded_rectangle(
            self, 1, 1, width - 1, 31, 8,
            fill=self.colours.board if self._choisi else self.colours.ground,
        )
        self.text = self.create_text(
            self.largeur_nue / 2, 16, text=self.caption,
            fill=self.colours.accent if self._choisi else self.colours.ink_pale,
            font=font(12),
        )
        if not self._count:
            return
        marque = dot_marker(self._count)
        centre = self.largeur_nue + self.PLACE_PASTILLE / 2 - 5
        self.create_oval(centre - 9, 7, centre + 9, 25,
                         fill=self.colours.accent, outline="")
        self.create_text(centre, 16, text=marque, fill=self.colours.board,
                         font=font(9, gras=True))

    def paint(self, choisi: bool) -> None:
        self._choisi = choisi
        self.itemconfigure(
            self.forme, fill=self.colours.board if choisi else self.colours.ground
        )
        self.itemconfigure(
            self.text,
            fill=self.colours.accent if choisi else self.colours.ink_pale,
        )

    def mark(self, count: int) -> None:
        """Places or removes the dot. Redraws only what changes."""
        count = max(0, count)
        if count == self._count:
            return
        self._count = count
        self._draw()

class ButtonBar(tk.Frame):
    """Buttons that wrap when the window is too narrow."""

    GAP = 9

    def __init__(self, parent: tk.Misc, colours: Palette) -> None:
        super().__init__(parent, bg=colours.board)
        self.colours = colours
        self._buttons: list[tuple[Button, int]] = []
        self._grille = (0, 0)
        self.bind("<Configure>", self._replacer)

    def add(self, button: Button, width: int) -> None:
        self._buttons.append((button, width))
        self._grille = (0, 0)  # forcer un replacement au prochain <Configure>

    def _replacer(self, _event: object = None) -> None:
        offerte = self.winfo_width()
        if offerte <= 1 or not self._buttons:
            return
        by_rank, colonne = button_grid(
            [width for _, width in self._buttons], offerte, self.GAP
        )
        if (by_rank, colonne) == self._grille:
            return
        self._grille = (by_rank, colonne)
        dernier_rang = (len(self._buttons) - 1) // by_rank
        for index, (button, _) in enumerate(self._buttons):
            rank = index // by_rank
            button.redimensionner(colonne)
            button.grid(
                row=rank,
                column=index % by_rank,
                sticky="ew",
                padx=(0, self.GAP) if index % by_rank < by_rank - 1 else 0,
                pady=(0, self.GAP) if rank < dernier_rang else 0,
            )

class Tabs(tk.Frame):
    """A bar of segments, in place of Tk's notebook."""

    def __init__(self, parent: tk.Misc, colours: Palette) -> None:
        super().__init__(parent, bg=colours.ground)
        self.colours = colours
        self.bar = tk.Frame(self, bg=colours.ground)
        self.bar.pack(fill="x")
        self.corps = tk.Frame(self, bg=colours.ground)
        self.corps.pack(fill="both", expand=True, pady=(14, 0))
        self._pages: dict[str, tk.Frame] = {}
        self._segments: dict[str, _Segment] = {}
        self._current: str | None = None

    def add(self, caption: str, shown: str = "") -> tk.Frame:
        """A tab, keyed by `caption` and labelled by `shown` where they differ.

        The key is what the code says -- `reveal("Conversation")` -- and stays
        the same in every language; the label is what the window paints. Kept
        apart because the two have different lifetimes: a translation changes,
        a key does not.
        """
        page = tk.Frame(self.corps, bg=self.colours.ground)
        self._pages[caption] = page
        def montrer(_shown: str, key: str = caption) -> None:
            self.reveal(key)

        segment = _Segment(self.bar, shown or caption, self.colours, montrer)
        segment.pack(side="left", padx=(0, 6))
        self._segments[caption] = segment
        if self._current is None:
            self.reveal(caption)
        return page

    def reveal(self, caption: str) -> None:
        for name, page in self._pages.items():
            if name == caption:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for name, segment in self._segments.items():
            segment.paint(name == caption)
        self._current = caption
        segment_courant = self._segments.get(caption)
        if segment_courant is not None:
            segment_courant.mark(0)

    @property
    def current(self) -> str | None:
        return self._current

    def mark(self, caption: str, count: int) -> None:
        """Puts a count on a tab, to flag it without opening it.

        The count clears itself when the tab is the one being looked at: a badge on
        the tab you are already on flags nothing.
        """
        segment = self._segments.get(caption)
        if segment is not None:
            segment.mark(0 if self._current == caption else count)
