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

from greffier.interface.style import Palette, police


def rectangle_arrondi(
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
        _points_arrondis(x1, y1, x2, y2, rayon),
        smooth=True, splinesteps=24, fill=fill, outline=outline,
    )


class Bouton(tk.Canvas):
    """Un bouton dessiné : coins arrondis, survol, deux allures."""

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        action: Callable[[], None],
        couleurs: Palette,
        principal: bool = False,
        largeur: int = 210,
        hauteur: int = 38,
    ) -> None:
        fond = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else couleurs.fond
        super().__init__(parent, width=largeur, height=hauteur,
                         highlightthickness=0, bg=fond)
        self.couleurs = couleurs
        self.principal = principal
        self.action = action
        self._actif = True
        self._forme = rectangle_arrondi(
            self, 1, 1, largeur - 1, hauteur - 1, 9,
            fill=self._fond_normal(), outline=couleurs.filet if not principal else "",
        )
        self._texte = self.create_text(
            largeur / 2, hauteur / 2, text=texte,
            fill=self._encre(), font=police(12, principal),
        )
        self.bind("<Enter>", lambda _e: self._peindre(survol=True))
        self.bind("<Leave>", lambda _e: self._peindre(survol=False))
        self.bind("<Button-1>", lambda _e: self.action() if self._actif else None)

    def _fond_normal(self) -> str:
        return self.couleurs.accent if self.principal else self.couleurs.carte

    def _encre(self) -> str:
        if not self._actif:
            return self.couleurs.calme
        return self.couleurs.accent_encre if self.principal else self.couleurs.encre

    def _peindre(self, survol: bool) -> None:
        if not self._actif:
            return
        if self.principal:
            self.itemconfigure(self._forme, fill=self.couleurs.accent)
        else:
            self.itemconfigure(
                self._forme, fill=self.couleurs.survol if survol else self.couleurs.carte
            )
        self.configure(cursor="pointinghand" if survol else "")

    def intituler(self, texte: str) -> None:
        self.itemconfigure(self._texte, text=texte)

    def activer(self, oui: bool) -> None:
        self._actif = oui
        self.itemconfigure(self._texte, fill=self._encre())
        self.itemconfigure(self._forme, fill=self._fond_normal() if oui else self.couleurs.survol)


class Liste(tk.Canvas):
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
        couleurs: Palette,
        largeur: int = 320,
        hauteur: int = 32,
        sur_choix: Callable[[str], None] | None = None,
    ) -> None:
        fond = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else couleurs.carte
        super().__init__(parent, width=largeur, height=hauteur,
                         highlightthickness=0, bg=fond)
        self.couleurs = couleurs
        self.largeur = largeur
        self.hauteur = hauteur
        self.sur_choix = sur_choix
        self._choix: list[tuple[str, str]] = []
        self._clef = ""
        self._actif = True
        self._forme = rectangle_arrondi(
            self, 1, 1, largeur - 1, hauteur - 1, 8,
            fill=couleurs.fond, outline=couleurs.filet,
        )
        self._texte = self.create_text(
            12, hauteur / 2, text="", anchor="w", fill=couleurs.encre, font=police(12),
        )
        # Un chevron, deux segments : la flèche pleine de Tk est le détail qui
        # trahit le plus le composant d'origine.
        pointe = largeur - 15
        milieu = hauteur / 2
        # Les points en une seule liste : la signature à coordonnées libres
        # n'accepte que deux points, un chevron en demande trois.
        self._chevron = self.create_line(
            [pointe - 5, milieu - 2, pointe, milieu + 3, pointe + 5, milieu - 2],
            fill=couleurs.encre_pale, width=1.6, capstyle="round", joinstyle="round",
        )
        self.bind("<Enter>", lambda _e: self._peindre(survol=True))
        self.bind("<Leave>", lambda _e: self._peindre(survol=False))
        self.bind("<Button-1>", self._deployer)

    def garnir(self, choix: list[tuple[str, str]], clef: str = "") -> None:
        """Pose les choix possibles, et sélectionne `clef` si elle en fait partie."""
        self._choix = list(choix)
        connues = [c for c, _ in self._choix]
        self._clef = clef if clef in connues else (connues[0] if connues else "")
        self._afficher()

    def valeur(self) -> str:
        return self._clef

    def choisir(self, clef: str) -> None:
        if clef != self._clef and clef in [c for c, _ in self._choix]:
            self._clef = clef
            self._afficher()

    def activer(self, oui: bool) -> None:
        self._actif = oui
        self.itemconfigure(self._texte,
                           fill=self.couleurs.encre if oui else self.couleurs.calme)
        self.itemconfigure(self._chevron,
                           fill=self.couleurs.encre_pale if oui else self.couleurs.calme)

    def _libelle(self) -> str:
        for clef, libelle in self._choix:
            if clef == self._clef:
                return libelle
        return ""

    def _afficher(self) -> None:
        # Tronqué au caractère près plutôt que laissé déborder sous le chevron :
        # un libellé long recouvrait la flèche et donnait un composant cassé.
        place = self.largeur - 34
        libelle = self._libelle()
        while libelle and self._largeur_du_texte(libelle) > place:
            libelle = libelle[:-2] + "…"
        self.itemconfigure(self._texte, text=libelle)

    def _largeur_du_texte(self, texte: str) -> int:
        essai = self.create_text(-1000, -1000, text=texte, anchor="w", font=police(12))
        gauche, _, droite, _ = self.bbox(essai)
        self.delete(essai)
        return int(droite - gauche)

    def _peindre(self, survol: bool) -> None:
        if not self._actif:
            return
        self.itemconfigure(
            self._forme,
            fill=self.couleurs.survol if survol else self.couleurs.fond,
            outline=self.couleurs.encre_pale if survol else self.couleurs.filet,
        )
        self.configure(cursor="pointinghand" if survol else "")

    def _deployer(self, _evenement: tk.Event | None = None) -> None:
        if not self._actif or not self._choix:
            return
        c = self.couleurs
        menu = tk.Menu(self, tearoff=0, font=police(12), bg=c.carte, fg=c.encre,
                       activebackground=c.survol, activeforeground=c.encre,
                       borderwidth=0, relief="flat", activeborderwidth=0)
        for clef, libelle in self._choix:
            marque = "✓ " if clef == self._clef else "   "
            # `functools.partial` et non une lambda à valeur par défaut : la
            # seconde ferme bien sur la bonne clef, mais mypy ne sait pas en
            # inférer le type, et l'intention se lit mieux ainsi.
            menu.add_command(label=f"{marque}{libelle}",
                             command=functools.partial(self._retenir, clef))
        # Déployé sous le composant, aligné à gauche : le menu prolonge le
        # champ au lieu de surgir sous le curseur.
        menu.post(self.winfo_rootx(), self.winfo_rooty() + self.hauteur)

    def _retenir(self, clef: str) -> None:
        change = clef != self._clef
        self._clef = clef
        self._afficher()
        if change and self.sur_choix is not None:
            self.sur_choix(clef)


class Defileur(tk.Canvas):
    """Un ascenseur fin et dessiné, à la place de celui de Tk — gris, à bords
    carrés, avec ses boutons flèche, il détonne dans une fenêtre par ailleurs
    tenue par une seule palette.

    Sert le même contrat que `ttk.Scrollbar` : `set(premier, dernier)` en
    entrée, `commande("moveto"|"scroll", …)` en sortie — un `Text` ou un
    `Treeview` ne voient pas la différence.
    """

    def __init__(
        self, parent: tk.Misc, couleurs: Palette,
        commande: Callable[..., None], largeur: int = 8,
    ) -> None:
        fond = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else couleurs.carte
        super().__init__(parent, width=largeur, highlightthickness=0, bg=fond)
        self.couleurs = couleurs
        self.commande = commande
        self.largeur = largeur
        self._premier = 0.0
        self._dernier = 1.0
        self._pouce = rectangle_arrondi(self, 1, 0, largeur - 1, 0, largeur / 2)
        self.bind("<Configure>", lambda _e: self._dessiner())
        self.bind("<Button-1>", self._deplacer)
        self.bind("<B1-Motion>", self._deplacer)
        self.bind("<Enter>", lambda _e: self._teinter(survol=True))
        self.bind("<Leave>", lambda _e: self._teinter(survol=False))
        self._teinter(survol=False)

    def set(self, premier: str | float, dernier: str | float) -> None:
        """Appelé par le widget suivi via `yscrollcommand` — signature imposée."""
        self._premier, self._dernier = float(premier), float(dernier)
        self._dessiner()

    def _teinter(self, survol: bool) -> None:
        # `filet`, prévu pour un trait à peine visible entre deux zones, se
        # fondait dans le fond : un ascenseur qu'on ne voit pas ne dit pas
        # qu'il y a davantage à lire. `calme` reste discret mais se remarque.
        self.itemconfigure(
            self._pouce, fill=self.couleurs.encre_pale if survol else self.couleurs.calme
        )

    def _dessiner(self) -> None:
        hauteur = self.winfo_height()
        # Rien à défiler : le pouce couvrirait toute la piste, autant le taire
        # plutôt que d'afficher un ascenseur qui ne mène nulle part.
        if hauteur <= 1 or self._dernier - self._premier >= 0.999:
            self.itemconfigure(self._pouce, state="hidden")
            return
        self.itemconfigure(self._pouce, state="normal")
        # Un pouce minimal même sur une très longue liste : en dessous d'une
        # certaine taille, il devient un point qu'on ne peut plus attraper.
        minimum = min(24, hauteur)
        haut = self._premier * hauteur
        bas = max(self._dernier * hauteur, haut + minimum)
        self.coords(
            self._pouce, *_points_arrondis(1, haut, self.largeur - 1, bas, self.largeur / 2)
        )

    def _deplacer(self, evenement: tk.Event) -> None:
        hauteur = self.winfo_height() or 1
        # Centre le pouce sous le doigt plutôt que d'aligner son sommet : sans
        # ça, cliquer plus bas que le pouce le fait sauter vers le haut.
        portee = self._dernier - self._premier
        cible = evenement.y / hauteur - portee / 2
        self.commande("moveto", max(0.0, min(1.0 - portee, cible)))


class Vumetre(tk.Canvas):
    """Une barre de niveau, arrondie, qui change de teinte avec l'intensité.

    La jauge glisse vers la valeur demandée plutôt que d'y sauter : la parole
    est faite de pics, et une barre qui saute à chaque tranche de 250 ms donne
    une impression de nervosité qu'un simple lissage suffit à corriger.
    """

    def __init__(
        self, parent: tk.Misc, couleurs: Palette, largeur: int = 300, hauteur: int = 8
    ) -> None:
        fond = parent.cget("bg") if isinstance(parent, tk.Canvas | tk.Frame) else couleurs.carte
        super().__init__(parent, width=largeur, height=hauteur,
                         highlightthickness=0, bg=fond)
        self.couleurs = couleurs
        self.largeur = largeur
        self.hauteur = hauteur
        rectangle_arrondi(self, 0, 0, largeur, hauteur, hauteur / 2,
                          fill=couleurs.filet, outline="")
        self._jauge = rectangle_arrondi(self, 0, 0, 1, hauteur, hauteur / 2,
                                        fill=couleurs.vert, outline="")
        self._valeur = 0.0
        self._cible = 0.0
        self._glisse: str | None = None

    def montrer(self, part: float) -> None:
        self._cible = max(0.0, min(1.0, part))
        if self._glisse is None:
            self._pas()

    def _pas(self) -> None:
        # Le glissement est réarmé toutes les 30 ms : si la fenêtre est
        # reconstruite entre deux pas — un changement de thème le fait — le
        # canevas n'existe plus et chaque pas restant lèverait une TclError
        # dans la boucle de Tk, sans autre effet que de salir le journal.
        if not self.winfo_exists():
            self._glisse = None
            return
        ecart = self._cible - self._valeur
        if abs(ecart) < 0.004:
            self._valeur = self._cible
            self._dessiner()
            self._glisse = None
            return
        # Un tiers de l'écart restant à chaque pas : vite sur un grand saut,
        # doux sur les derniers pourcents.
        self._valeur += ecart * 0.32
        self._dessiner()
        self._glisse = self.after(30, self._pas)

    def _dessiner(self) -> None:
        part = self._valeur
        if part <= 0.01:
            self.itemconfigure(self._jauge, state="hidden")
            return
        self.itemconfigure(self._jauge, state="normal")
        longueur = max(self.hauteur, part * self.largeur)
        self.coords(self._jauge, *_points_arrondis(0, 0, longueur, self.hauteur,
                                                   self.hauteur / 2))
        # Le vert au-dessous de 70 %, l'ambre au-delà : une entrée qui frôle la
        # saturation dégrade la transcription, autant que ça se voie.
        self.itemconfigure(
            self._jauge, fill=self.couleurs.ambre if part > 0.7 else self.couleurs.vert
        )


def _points_arrondis(
    x1: float, y1: float, x2: float, y2: float, rayon: float
) -> list[float]:
    rayon = min(rayon, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    return [
        x1 + rayon, y1, x2 - rayon, y1, x2, y1, x2, y1 + rayon,
        x2, y2 - rayon, x2, y2, x2 - rayon, y2, x1 + rayon, y2,
        x1, y2, x1, y2 - rayon, x1, y1 + rayon, x1, y1,
    ]


class _Segment(tk.Canvas):
    """Un onglet dessiné, qui sait se peindre choisi ou non."""

    def __init__(self, parent: tk.Misc, intitule: str, couleurs: Palette,
                 action: Callable[[str], None]) -> None:
        largeur = len(intitule) * 9 + 34
        super().__init__(parent, width=largeur, height=32,
                         highlightthickness=0, bg=couleurs.fond)
        self.intitule = intitule
        self.couleurs = couleurs
        self.forme = rectangle_arrondi(self, 1, 1, largeur - 1, 31, 8,
                                       fill=couleurs.fond)
        self.texte = self.create_text(largeur / 2, 16, text=intitule,
                                      fill=couleurs.encre_pale, font=police(12))
        self.bind("<Button-1>", lambda _e: action(self.intitule))
        self.bind("<Enter>", lambda _e: self.configure(cursor="pointinghand"))
        self.bind("<Leave>", lambda _e: self.configure(cursor=""))

    def peindre(self, choisi: bool) -> None:
        self.itemconfigure(
            self.forme, fill=self.couleurs.carte if choisi else self.couleurs.fond
        )
        self.itemconfigure(
            self.texte,
            fill=self.couleurs.accent if choisi else self.couleurs.encre_pale,
        )


class Onglets(tk.Frame):
    """Une barre de segments, à la place du bandeau d'onglets de Tk."""

    def __init__(self, parent: tk.Misc, couleurs: Palette) -> None:
        super().__init__(parent, bg=couleurs.fond)
        self.couleurs = couleurs
        self.barre = tk.Frame(self, bg=couleurs.fond)
        self.barre.pack(fill="x")
        self.corps = tk.Frame(self, bg=couleurs.fond)
        self.corps.pack(fill="both", expand=True, pady=(14, 0))
        self._pages: dict[str, tk.Frame] = {}
        self._segments: dict[str, _Segment] = {}
        self._courant: str | None = None

    def ajouter(self, intitule: str) -> tk.Frame:
        page = tk.Frame(self.corps, bg=self.couleurs.fond)
        self._pages[intitule] = page
        segment = _Segment(self.barre, intitule, self.couleurs, self.montrer)
        segment.pack(side="left", padx=(0, 6))
        self._segments[intitule] = segment
        if self._courant is None:
            self.montrer(intitule)
        return page

    def montrer(self, intitule: str) -> None:
        for nom, page in self._pages.items():
            if nom == intitule:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for nom, segment in self._segments.items():
            segment.peindre(nom == intitule)
        self._courant = intitule

    @property
    def courant(self) -> str | None:
        return self._courant
