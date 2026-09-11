"""La palette et la typographie, éprouvées sans ouvrir de fenêtre.

Tk ne démarre pas sur un exécuteur d'intégration continue, et de toute façon
comparer des pixels ne dit rien d'utile. Ce qui se teste ici, c'est ce qui a
réellement cassé : une couleur invalide fait tomber Tk au dessin, et une palette
incomplète laisse un texte illisible sur son fond.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from greffier.interface.style import CLAIR, SOMBRE, Palette, font, palette

TEINTE = re.compile(r"^#[0-9a-fA-F]{6}$")


def both_palettes(palette: Palette) -> dict[str, str]:
    return {
        name: getattr(palette, name)
        for name in (
            "ground", "board", "ink", "ink_pale", "rule", "accent",
            "accent_ink", "active", "calm", "green", "amber", "hover",
        )
    }


class TestThePalettes:
    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_every_colour_is_a_valid_shade(self, palette: Palette) -> None:
        # Une couleur mal écrite ne se voit pas à la lecture : elle fait tomber
        # Tk au premier dessin. C'est arrivé, avec des caractères non latins
        # glissés dans une valeur hexadécimale.
        for name, value in both_palettes(palette).items():
            assert TEINTE.match(value), f"{name} = {value!r}"

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_the_text_contrasts_with_its_ground(self, palette: Palette) -> None:
        assert _contrast(palette.ink, palette.board) >= 4.5
        assert _contrast(palette.ink, palette.ground) >= 4.5
        assert _contrast(palette.accent_ink, palette.accent) >= 4.5

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_the_pale_text_stays_readable(self, palette: Palette) -> None:
        # Assoupli à 3:1, la valeur admise pour du texte secondaire.
        assert _contrast(palette.ink_pale, palette.board) >= 3.0

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_the_accent_is_a_real_shade(self, palette: Palette) -> None:
        """Il valait le noir de l'encre : la fenêtre était entièrement grise et
        rien ne guidait l'œil. Un accent doit se distinguer de l'encre, se voir
        sur la carte, et ne pas se confondre avec un état."""
        assert palette.accent != palette.ink
        assert _contrast(palette.accent, palette.board) >= 3.0
        for state in (palette.active, palette.green, palette.amber):
            assert palette.accent != state

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_the_rule_can_be_seen(self, palette: Palette) -> None:
        """Mesuré à 1,28:1, il ne se voyait pas : bordures et séparateurs
        disparaissaient, et l'interface paraissait plate quoi qu'on fasse."""
        assert _contrast(palette.rule, palette.board) >= 1.35
        assert _contrast(palette.rule, palette.ground) >= 1.3

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_the_states_can_be_told_apart(self, palette: Palette) -> None:
        # Rouge d'enregistrement, ambre de pause, gris de repos : trois états
        # qu'on doit pouvoir séparer d'un coup d'œil.
        etats = {palette.active, palette.amber, palette.calm}
        assert len(etats) == 3

    def test_the_two_palettes_cover_the_same_roles(self) -> None:
        assert both_palettes(CLAIR).keys() == both_palettes(SOMBRE).keys()

    def test_light_and_dark_are_really_the_other_way_round(self) -> None:
        assert _luminance(CLAIR.ground) > _luminance(CLAIR.ink)
        assert _luminance(SOMBRE.ground) < _luminance(SOMBRE.ink)


class TestTheFont:
    def test_the_size_is_given_in_pixels(self) -> None:
        # Négative, donc lue en pixels : en points, X11 rend un tiers plus grand
        # que macOS et les libellés débordent de leurs boutons.
        assert font(13)[1] == -13

    def test_the_fallback_family_is_one_tk_guarantees(self) -> None:
        # Tk n'assure « Helvetica » — comme « Courier » et « Times » — que
        # parce qu'il la fait pointer vers la police de la plateforme. Toute
        # autre famille dépend de fontconfig, que le Tk de l'interpréteur posé
        # par l'installeur n'embarque pas : elle y retomberait sur une bitmap.
        assert font(12)[0] in {"SF Pro Text", "Segoe UI", "Helvetica"}

    def test_bold_can_be_asked_for(self) -> None:
        assert font(12, gras=True)[2] == "bold"
        assert font(12)[2] == "normal"

    def test_a_family_is_always_given(self) -> None:
        # Sans famille, Tk retombe sur une police à empattements et l'interface
        # change d'allure d'un système à l'autre.
        assert font(12)[0]


def _luminance(teinte: str) -> float:
    """Luminance relative, telle que la définissent les règles d'accessibilité."""
    channels = [int(teinte[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lineaires = [
        canal / 12.92 if canal <= 0.04045 else ((canal + 0.055) / 1.055) ** 2.4
        for canal in channels
    ]
    return 0.2126 * lineaires[0] + 0.7152 * lineaires[1] + 0.0722 * lineaires[2]


def _contrast(premier: str, second: str) -> float:
    a, b = _luminance(premier), _luminance(second)
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


class TestChoosingTheTheme:
    """Le thème est un réglage, plus seulement une lecture du système."""

    def test_a_theme_asked_for_is_returned_as_it_is(self) -> None:
        assert palette("clair") is CLAIR
        assert palette("sombre") is SOMBRE

    def test_with_nothing_asked_the_system_decides(self, monkeypatch) -> None:
        import greffier.interface.style as style

        monkeypatch.setattr(style, "system_is_dark", lambda: True)
        assert style.palette("systeme") is SOMBRE
        monkeypatch.setattr(style, "system_is_dark", lambda: False)
        assert style.palette("systeme") is CLAIR

    def test_an_unknown_value_does_not_bring_the_window_down(self, monkeypatch) -> None:
        """Un fichier écrit à la main peut porter n'importe quoi : on se rabat
        sur le système plutôt que de refuser de s'ouvrir."""
        import greffier.interface.style as style

        monkeypatch.setattr(style, "system_is_dark", lambda: False)
        assert style.palette("fluo") is CLAIR



class TestTheThemeOfTheSystem:
    """Les trois systèmes disent leur préférence, chacun à sa façon.

    Ne demander qu'à macOS laissait un bureau réglé en sombre recevoir une
    interface claire, ce qui saute aux yeux à côté des autres fenêtres.
    """

    def _answer(self, monkeypatch, answers):
        from greffier.interface import style

        def faux(command, **_):
            for motif, output in answers.items():
                if motif in " ".join(command):
                    return SimpleNamespace(returncode=0, stdout=output)
            return SimpleNamespace(returncode=1, stdout="")

        monkeypatch.setattr(style.subprocess, "run", faux)

    def test_macos_answers_dark(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Darwin")
        self._answer(monkeypatch, {"AppleInterfaceStyle": "Dark\n"})
        assert style.system_is_dark()

    def test_windows_reads_its_key_the_other_way_round(self, monkeypatch):
        """La clé dit si les applications sont en thème **clair** : 0 est sombre."""
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Windows")
        self._answer(monkeypatch, {
            "AppsUseLightTheme": "    AppsUseLightTheme    REG_DWORD    0x0\n"})
        assert style.system_is_dark()

    def test_windows_in_light(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Windows")
        self._answer(monkeypatch, {
            "AppsUseLightTheme": "    AppsUseLightTheme    REG_DWORD    0x1\n"})
        assert not style.system_is_dark()

    def test_linux_through_the_freedesktop_portal(self, monkeypatch):
        """La clé portable, que GNOME comme KDE renseignent."""
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")
        self._answer(monkeypatch, {"freedesktop.portal": "(<<uint32 1>>,)\n"})
        assert style.system_is_dark()

    def test_linux_with_no_portal_falls_back_to_gnome(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")
        self._answer(monkeypatch, {"gsettings": "'prefer-dark'\n"})
        assert style.system_is_dark()

    def test_a_silent_system_gives_the_light_theme(self, monkeypatch):
        """Un repli clair est acceptable ; une fenêtre qui n'ouvre pas ne l'est pas."""
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")
        self._answer(monkeypatch, {})
        assert not style.system_is_dark()

    def test_a_missing_command_does_not_raise(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")

        def absente(*_a, **_k):
            raise FileNotFoundError("gdbus")

        monkeypatch.setattr(style.subprocess, "run", absente)
        assert not style.system_is_dark()
