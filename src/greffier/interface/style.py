"""Palette et typographie, sans une ligne de Tk.

Séparé des widgets pour deux raisons. La première est architecturale : une
couleur et une taille de police ne dépendent d'aucune boîte à outils. La seconde
est pratique et fut découverte en intégration continue : l'image « python:3.13-slim »
n'embarque pas « libtk8.6.so », donc tout module qui importe « tkinter » y est
inimportable, tests compris. Ce qui se teste vit donc ici.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Les rôles, pas les couleurs : c'est ce qui permet d'avoir deux thèmes.

    Chaque valeur est éprouvée par `tests/interface/test_style.py`, contrastes
    compris. Deux mesures y comptent plus que le goût : le texte doit passer
    4,5:1 sur son fond, et le **filet** doit rester perceptible — mesuré à
    1,28:1, il ne se voyait pas, et une interface dont les bordures sont
    invisibles paraît plate quoi qu'on fasse par ailleurs.
    """

    #: L'accent porte l'action principale, l'onglet choisi et le liseré de
    #: saisie active. Il valait le noir de l'encre : la fenêtre était donc
    #: entièrement grise, et rien ne guidait l'œil. Un indigo, choisi loin du
    #: rouge d'enregistrement et des vumètres pour qu'aucun état ne s'y confonde.
    fond: str
    carte: str
    encre: str
    encre_pale: str
    filet: str
    accent: str
    accent_encre: str
    actif: str
    calme: str
    vert: str
    ambre: str
    survol: str


CLAIR = Palette(
    fond="#f5f5f7",
    carte="#ffffff",
    encre="#1d1d20",
    encre_pale="#6e6e78",
    filet="#d2d2da",
    accent="#3b4cca",
    accent_encre="#ffffff",
    actif="#d64541",
    calme="#b4b4bd",
    vert="#1e8a58",
    ambre="#b8860b",
    survol="#f0f0f3",
)

SOMBRE = Palette(
    fond="#1a1a1d",
    carte="#242428",
    encre="#f2f2f4",
    encre_pale="#9a9aa4",
    filet="#3d3d46",
    accent="#7b8cf0",
    accent_encre="#1a1a1d",
    actif="#e05c58",
    calme="#55555e",
    vert="#3fb47c",
    ambre="#d9a441",
    survol="#2e2e34",
)


def systeme_en_sombre() -> bool:
    """Suit le réglage du système, plutôt que d'imposer un goût."""
    if platform.system() != "Darwin":
        return False
    fait = subprocess.run(
        ["defaults", "read", "-g", "AppleInterfaceStyle"],
        capture_output=True, text=True, check=False,
    )
    return fait.stdout.strip() == "Dark"


def palette(theme: str = "systeme") -> Palette:
    """La palette demandée, ou celle du système quand on ne demande rien."""
    if theme == "clair":
        return CLAIR
    if theme == "sombre":
        return SOMBRE
    return SOMBRE if systeme_en_sombre() else CLAIR


def police(taille: int, gras: bool = False) -> tuple[str, int, str]:
    """La police de l'interface du système, avec un repli sûr.

    La taille part en négatif, ce que Tk lit comme des pixels. Un nombre positif
    serait des points, qu'il convertit selon la résolution annoncée par l'écran :
    macOS en annonce soixante-douze par pouce, où points et pixels se confondent,
    contre près de cent sous X11. À taille égale, la même interface y grandissait
    donc d'un tiers, et les libellés débordaient de leurs boutons.
    """
    familles = {
        "Darwin": "SF Pro Text",
        "Windows": "Segoe UI",
    }
    # Tk ne garantit que « Courier », « Helvetica » et « Times » sur les trois
    # systèmes, et les fait pointer vers les polices de la plateforme. Nommer
    # « DejaVu Sans » semblait plus juste sous Linux, mais l'interpréteur que
    # pose l'installeur embarque un Tk construit sans fontconfig : il n'expose
    # que les familles X11 historiques, et tout nom qu'il ignore retombe sur
    # « fixed » — une bitmap qui ne s'échelonne pas.
    famille = familles.get(platform.system(), "Helvetica")
    return (famille, -taille, "bold" if gras else "normal")


# Descendues de `fenetre`, où elles étaient privées et donc jamais éprouvées.
# `degrade` tomberait aujourd'hui sur une couleur mal formée sans qu'aucun test
# ne le dise, et c'est de la couleur, pas du Tk : sa place est ici.
def degrade(depuis: str, vers: str, part: float) -> str:
    """Une couleur entre deux autres, en hexadécimal — le fondu du point rouge."""
    a = tuple(int(depuis[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(vers[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * part):02x}" for x, y in zip(a, b, strict=True))


def police_titre(taille: int) -> tuple[str, int, str]:
    """Une empreinte plus éditoriale pour le nom de la réunion.

    Le seul texte de la fenêtre qui n'a pas besoin de ressembler à un bouton.
    Georgia est du système sur macOS et Windows ; ailleurs « Times », que Tk
    garantit et fait pointer vers la sérif de la plateforme, comme le repli de
    `police`. La taille suit la même règle : négative, donc en pixels.
    """
    famille = {"Darwin": "Georgia", "Windows": "Georgia"}.get(platform.system(), "Times")
    return (famille, -taille, "bold")
