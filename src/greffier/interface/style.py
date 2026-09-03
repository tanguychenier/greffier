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
    """La police de l'interface du système, avec un repli sûr."""
    familles = {
        "Darwin": "SF Pro Text",
        "Windows": "Segoe UI",
    }
    famille = familles.get(platform.system(), "DejaVu Sans")
    return (famille, taille, "bold" if gras else "normal")
