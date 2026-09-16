"""Palette and typography, without a line of Tk."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Roles, not colours: that is what makes two themes possible.

    Every value is measured by the tests, contrasts included. Two figures matter
    more than taste: text must clear 4.5:1 on its ground, and the rule must stay
    visible, measured at 1.28:1 it did not, and an interface whose borders are
    invisible looks flat whatever else is done.
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
    """Follows the system setting rather than imposing a taste."""
    system = platform.system()
    if system == "Darwin":
        return _output(["defaults", "read", "-g", "AppleInterfaceStyle"]) == "Dark"
    if system == "Windows":
        read_ = _output([
            "reg", "query",
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "/v", "AppsUseLightTheme",
        ])
        return "0x0" in read_
    portal = _output([
        "gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Desktop",
        "--object-path", "/org/freedesktop/portal/desktop",
        "--method", "org.freedesktop.portal.Settings.Read",
        "org.freedesktop.appearance", "color-scheme",
    ])
    if portal:
        return "uint32 1" in portal
    setting = _output(["gsettings", "get", "org.gnome.desktop.interface",
                       "color-scheme"])
    if setting:
        return "dark" in setting.lower()
    theme = _output(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    return "dark" in theme.lower()

def _output(command: list[str]) -> str:
    """What a command writes, or nothing when it is missing."""
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              check=False, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""

def palette(theme: str = "systeme") -> Palette:
    """The palette asked for, or the system's when following it."""
    if theme == "clair":
        return CLAIR
    if theme == "sombre":
        return SOMBRE
    return SOMBRE if system_is_dark() else CLAIR

def font(size: int, bold: bool = False) -> tuple[str, int, str]:
    """The system interface font, with a fallback."""
    families = {
        "Darwin": "SF Pro Text",
        "Windows": "Segoe UI",
    }
    family = families.get(platform.system(), "Helvetica")
    return (family, -size, "bold" if bold else "normal")

def blend(since: str, into: str, part: float) -> str:
    """A colour between two others, in hexadecimal."""
    a = tuple(int(since[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(into[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * part):02x}" for x, y in zip(a, b, strict=True))

def title_font(size: int) -> tuple[str, int, str]:
    """A more editorial face for the meeting's name."""
    family = {"Darwin": "Georgia", "Windows": "Georgia"}.get(platform.system(), "Times")
    return (family, -size, "bold")
