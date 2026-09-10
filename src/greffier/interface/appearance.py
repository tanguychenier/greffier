"""Les widgets dessinés de la fenêtre.

Les widgets fournis par Tk datent, et aucun réglage de thème ne les rattrape :
un bouton `ttk` reste un bouton gris à bord carré, une `Progressbar` reste une
barre rayée. Ce qui suit les remplace par des formes dessinées sur un `Canvas`,
avec des angles arrondis, une palette tenue en un seul endroit et des états de
survol. Tk sait faire cela très bien : il dessine ce qu'on lui demande.

La palette et la typographie vivent dans `style`, qui n'importe pas Tk : elles
se testent sans écran, et l'image d'intégration continue n'a pas Tk.
"""

from __future__ import annotations

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
    """Un rectangle à coins arrondis, que Tk ne fournit pas.

    Assemblé en un seul polygone lissé : deux arcs et un rectangle laisseraient
    des jointures visibles dès qu'on change la couleur de remplissage.
    """
    return toile.create_polygon(
        _rounded_points(x1, y1, x2, y2, rayon),
        smooth=True, splinesteps=24, fill=fill, outline=outline,
    )

class Button(tk.Canvas):
    """Un bouton dessiné : coins arrondis, survol, deux allures."""

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
        """Reprend la largeur du bouton, forme et texte recentré compris.

        Nécessaire pour qu'une barre d'actions soit une vraie grille : des
        boutons de largeurs différentes ne s'alignent pas d'un rang à l'autre,
        et une barre dont les bords ne tombent pas ensemble se lit comme
        bâclée.
        """
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

    def set_caption(self, text: str) -> None:
        self.itemconfigure(self._text, text=text)

    def highlight(self, principal: bool) -> None:
        """Bascule entre l'allure d'action principale et l'allure ordinaire.

        Un bouton qui change d'état doit le montrer : « Lucie participe » en
        creux et « Faire taire Lucie » en plein ne se confondent pas d'un coup
        d'œil, ce qu'un intitulé seul ne garantit pas quand on est en réunion.
        """
        if principal == self.principal:
            return
        self.principal = principal
        self.itemconfigure(self._forme, fill=self._plain_background(),
                           outline="" if principal else self.colours.rule)
        self.itemconfigure(self._text, fill=self._ink(),
                           font=font(12, principal))

    def activer(self, oui: bool) -> None:
        self._active = oui
        self.itemconfigure(self._text, fill=self._ink())
        self.itemconfigure(
            self._forme,
            fill=self._plain_background() if oui else self.colours.hover,
        )

class Listing(tk.Canvas):
    """Une liste déroulante dessinée, à la place de celle de Tk.

    `ttk.Combobox` arrive avec le bouton fléché carré et gris du thème
    « clam » : à côté des boutons et des ascenseurs dessinés, elle jure — même
    en lui passant les couleurs de la palette, la flèche reste un bouton séparé
    par un liseré, et le menu déployé garde ses bords carrés. Ici, tout est
    dessiné : même arrondi, même liseré, même survol que le reste.

    Le composant porte lui-même ses couples (clef, libellé) : l'appelant règle
    et lit des **clefs**, jamais le texte affiché — c'est ce qui évitait, dans
    la version précédente, de retrouver la clef en comparant des libellés.
    """

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

    def fill_menu(self, choix: list[tuple[str, str]], key: str = "") -> None:
        """Pose les choix possibles, et sélectionne `clef` si elle en fait partie."""
        self._choix = list(choix)
        connues = [c for c, _ in self._choix]
        self._key = key if key in connues else (connues[0] if connues else "")
        self._show()

    def value(self) -> str:
        return self._key

    def choose(self, key: str) -> None:
        if key != self._key and key in [c for c, _ in self._choix]:
            self._key = key
            self._show()

    def activer(self, oui: bool) -> None:
        self._active = oui
        self.itemconfigure(self._text,
                           fill=self.colours.ink if oui else self.colours.calm)
        self.itemconfigure(self._chevron,
                           fill=self.colours.ink_pale if oui else self.colours.calm)

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
        gauche, _, droite, _ = self.bbox(essai)
        self.delete(essai)
        return int(droite - gauche)

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
        menu = tk.Menu(self, tearoff=0, font=font(12), bg=c.board, fg=c.ink,
                       activebackground=c.hover, activeforeground=c.ink,
                       borderwidth=0, relief="flat", activeborderwidth=0)
        for key, label_text in self._choix:
            marque = "✓ " if key == self._key else "   "
            menu.add_command(label=f"{marque}{label_text}",
                             command=functools.partial(self._retenir, key))
        menu.post(self.winfo_rootx(), self.winfo_rooty() + self.height)

    def _retenir(self, key: str) -> None:
        change = key != self._key
        self._key = key
        self._show()
        if change and self.on_choice is not None:
            self.on_choice(key)

class Scroller(tk.Canvas):
    """Un ascenseur fin et dessiné, à la place de celui de Tk — gris, à bords
    carrés, avec ses boutons flèche, il détonne dans une fenêtre par ailleurs
    tenue par une seule palette.

    Sert le même contrat que `ttk.Scrollbar` : `set(premier, dernier)` en
    entrée, `commande("moveto"|"scroll", …)` en sortie — un `Text` ou un
    `Treeview` ne voient pas la différence.
    """

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
        """Appelé par le widget suivi via `yscrollcommand` — signature imposée."""
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
    """Une barre de niveau, arrondie, qui change de teinte avec l'intensité.

    La jauge glisse vers la valeur demandée plutôt que d'y sauter : la parole
    est faite de pics, et une barre qui saute à chaque tranche de 250 ms donne
    une impression de nervosité qu'un simple lissage suffit à corriger.
    """

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
            self._pas()

    def _pas(self) -> None:
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
        self._glisse = self.after(30, self._pas)

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
    """Un onglet dessiné, qui sait se peindre choisi ou non — et porter un compte.

    Le compte est une pastille, comme le panier d'un site marchand : on doit
    savoir qu'il y a quelque chose à voir **sans** être sur l'onglet, et sans
    qu'une fenêtre surgisse au milieu d'une réunion. Elle n'apparaît qu'à partir
    de un, et le segment s'élargit pour lui faire place plutôt que de réserver
    un vide permanent.
    """

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
        """Redessine tout : la largeur change avec la pastille.

        Redessiner plutôt que déplacer, parce que la forme arrondie est faite
        de segments dont on ne peut pas changer la largeur sans les refaire.
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
        """Pose ou retire la pastille. Ne redessine que si le compte a changé."""
        count = max(0, count)
        if count == self._count:
            return
        self._count = count
        self._draw()

class ButtonBar(tk.Frame):
    """Des boutons qui passent à la ligne quand la largeur manque.

    `pack(side="left")` ne revient jamais à la ligne : le septième bouton de
    l'onglet Réunions sortait de la fenêtre, invisible et inatteignable —
    exactement le défaut que le module met en garde contre, en haut de ce
    fichier, à propos d'un bouton poussé hors du cadre.

    Le nombre de colonnes est recalculé à chaque redimensionnement, d'après la
    largeur réellement offerte. Une grille et non un `pack` : c'est ce qui
    permet de placer les boutons sur plusieurs rangs sans les mesurer un à un.
    """

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
    """Une barre de segments, à la place du bandeau d'onglets de Tk."""

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

    def add(self, caption: str) -> tk.Frame:
        page = tk.Frame(self.corps, bg=self.colours.ground)
        self._pages[caption] = page
        segment = _Segment(self.bar, caption, self.colours, self.reveal)
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
        """Pose un compte sur un onglet, pour le signaler sans l'ouvrir.

        Le compte s'efface de lui-même quand l'onglet est celui qu'on regarde :
        une pastille sur l'onglet où l'on se trouve ne signale plus rien.
        """
        segment = self._segments.get(caption)
        if segment is not None:
            segment.mark(0 if self._current == caption else count)
