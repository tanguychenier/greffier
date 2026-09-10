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

    ground: str
    board: str
    ink: str
    ink_pale: str
    rule: str
    accent: str
    accent_ink: str
    active: str
    calm: str
    green: str
    amber: str
    hover: str

CLAIR = Palette(
    ground="#f5f5f7",
    board="#ffffff",
    ink="#1d1d20",
    ink_pale="#6e6e78",
    rule="#d2d2da",
    accent="#3b4cca",
    accent_ink="#ffffff",
    active="#d64541",
    calm="#b4b4bd",
    green="#1e8a58",
    amber="#b8860b",
    hover="#f0f0f3",
)

SOMBRE = Palette(
    ground="#1a1a1d",
    board="#242428",
    ink="#f2f2f4",
    ink_pale="#9a9aa4",
    rule="#3d3d46",
    accent="#7b8cf0",
    accent_ink="#1a1a1d",
    active="#e05c58",
    calm="#55555e",
    green="#3fb47c",
    amber="#d9a441",
    hover="#2e2e34",
)

def system_is_dark() -> bool:
    """Suit le réglage du système, plutôt que d'imposer un goût.

    Les trois systèmes le disent, chacun à sa façon, et aucun ne coûte plus de
    quelques millisecondes. Ne demander qu'à macOS laissait un bureau réglé en
    sombre recevoir une interface claire, ce qui saute aux yeux à côté de toutes
    les autres fenêtres.
    """
    system = platform.system()
    if system == "Darwin":
        return _output(["defaults", "read", "-g", "AppleInterfaceStyle"]) == "Dark"
    if system == "Windows":
        # 0 veut dire sombre : la clé dit si les applications utilisent le
        # thème **clair**, ce qui se lit à l'envers de ce qu'on cherche.
        lu = _output([
            "reg", "query",
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "/v", "AppsUseLightTheme",
        ])
        return "0x0" in lu
    # Linux et les autres : la clé portable de freedesktop d'abord, que GNOME,
    # KDE et les bureaux récents renseignent tous ; le réglage GNOME ensuite,
    # pour les versions qui ne l'exposent pas encore.
    portail = _output([
        "gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Desktop",
        "--object-path", "/org/freedesktop/portal/desktop",
        "--method", "org.freedesktop.portal.Settings.Read",
        "org.freedesktop.appearance", "color-scheme",
    ])
    if portail:
        # La réponse est un variant imbriqué, « (<<uint32 1>>,) » : 1 est
        # sombre, 2 est clair, 0 est « sans préférence ».
        return "uint32 1" in portail
    reglage = _output(["gsettings", "get", "org.gnome.desktop.interface",
                       "color-scheme"])
    if reglage:
        return "dark" in reglage.lower()
    theme = _output(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    return "dark" in theme.lower()

def _output(command: list[str]) -> str:
    """Ce qu'une commande écrit, ou rien si elle manque ou échoue.

    Rien est le cas courant : `gdbus` n'existe pas sur un poste sans D-Bus,
    `reg` pas hors de Windows. Un thème clair est un repli acceptable, une
    fenêtre qui ne s'ouvre pas ne l'est pas.
    """
    try:
        fait = subprocess.run(command, capture_output=True, text=True,
                              check=False, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return ""
    return fait.stdout.strip() if fait.returncode == 0 else ""

def palette(theme: str = "systeme") -> Palette:
    """La palette demandée, ou celle du système quand on ne demande rien."""
    if theme == "clair":
        return CLAIR
    if theme == "sombre":
        return SOMBRE
    return SOMBRE if system_is_dark() else CLAIR

def font(taille: int, gras: bool = False) -> tuple[str, int, str]:
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
def blend(depuis: str, vers: str, part: float) -> str:
    """Une couleur entre deux autres, en hexadécimal — le fondu du point rouge."""
    a = tuple(int(depuis[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(vers[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * part):02x}" for x, y in zip(a, b, strict=True))

def title_font(taille: int) -> tuple[str, int, str]:
    """Une empreinte plus éditoriale pour le nom de la réunion.

    Le seul texte de la fenêtre qui n'a pas besoin de ressembler à un bouton.
    Georgia est du système sur macOS et Windows ; ailleurs « Times », que Tk
    garantit et fait pointer vers la sérif de la plateforme, comme le repli de
    `police`. La taille suit la même règle : négative, donc en pixels.
    """
    famille = {"Darwin": "Georgia", "Windows": "Georgia"}.get(platform.system(), "Times")
    return (famille, -taille, "bold")
