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


def toutes(palette: Palette) -> dict[str, str]:
    return {
        name: getattr(palette, name)
        for name in (
            "ground", "board", "ink", "ink_pale", "rule", "accent",
            "accent_ink", "active", "calm", "green", "amber", "hover",
        )
    }


class TestPalettes:
    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_chaque_couleur_est_une_teinte_valide(self, palette: Palette) -> None:
        # Une couleur mal écrite ne se voit pas à la lecture : elle fait tomber
        # Tk au premier dessin. C'est arrivé, avec des caractères non latins
        # glissés dans une valeur hexadécimale.
        for name, value in toutes(palette).items():
            assert TEINTE.match(value), f"{name} = {value!r}"

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_le_texte_contraste_avec_son_fond(self, palette: Palette) -> None:
        assert _contraste(palette.ink, palette.board) >= 4.5
        assert _contraste(palette.ink, palette.ground) >= 4.5
        assert _contraste(palette.accent_ink, palette.accent) >= 4.5

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_le_texte_pale_reste_lisible(self, palette: Palette) -> None:
        # Assoupli à 3:1, la valeur admise pour du texte secondaire.
        assert _contraste(palette.ink_pale, palette.board) >= 3.0

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_l_accent_est_une_vraie_teinte(self, palette: Palette) -> None:
        """Il valait le noir de l'encre : la fenêtre était entièrement grise et
        rien ne guidait l'œil. Un accent doit se distinguer de l'encre, se voir
        sur la carte, et ne pas se confondre avec un état."""
        assert palette.accent != palette.ink
        assert _contraste(palette.accent, palette.board) >= 3.0
        for state in (palette.active, palette.green, palette.amber):
            assert palette.accent != state

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_le_filet_se_voit(self, palette: Palette) -> None:
        """Mesuré à 1,28:1, il ne se voyait pas : bordures et séparateurs
        disparaissaient, et l'interface paraissait plate quoi qu'on fasse."""
        assert _contraste(palette.rule, palette.board) >= 1.35
        assert _contraste(palette.rule, palette.ground) >= 1.3

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_les_etats_se_distinguent(self, palette: Palette) -> None:
        # Rouge d'enregistrement, ambre de pause, gris de repos : trois états
        # qu'on doit pouvoir séparer d'un coup d'œil.
        etats = {palette.active, palette.amber, palette.calm}
        assert len(etats) == 3

    def test_les_deux_palettes_couvrent_les_memes_roles(self) -> None:
        assert toutes(CLAIR).keys() == toutes(SOMBRE).keys()

    def test_le_clair_et_le_sombre_sont_bien_inverses(self) -> None:
        assert _luminance(CLAIR.ground) > _luminance(CLAIR.ink)
        assert _luminance(SOMBRE.ground) < _luminance(SOMBRE.ink)


class TestPolice:
    def test_la_taille_est_donnee_en_pixels(self) -> None:
        # Négative, donc lue en pixels : en points, X11 rend un tiers plus grand
        # que macOS et les libellés débordent de leurs boutons.
        assert font(13)[1] == -13

    def test_la_famille_de_repli_est_garantie_par_tk(self) -> None:
        # Tk n'assure « Helvetica » — comme « Courier » et « Times » — que
        # parce qu'il la fait pointer vers la police de la plateforme. Toute
        # autre famille dépend de fontconfig, que le Tk de l'interpréteur posé
        # par l'installeur n'embarque pas : elle y retomberait sur une bitmap.
        assert font(12)[0] in {"SF Pro Text", "Segoe UI", "Helvetica"}

    def test_le_gras_se_demande(self) -> None:
        assert font(12, gras=True)[2] == "bold"
        assert font(12)[2] == "normal"

    def test_une_famille_est_toujours_donnee(self) -> None:
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


def _contraste(premier: str, second: str) -> float:
    a, b = _luminance(premier), _luminance(second)
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


class TestChoixDuTheme:
    """Le thème est un réglage, plus seulement une lecture du système."""

    def test_un_theme_demande_est_rendu_tel_quel(self) -> None:
        assert palette("clair") is CLAIR
        assert palette("sombre") is SOMBRE

    def test_sans_demande_le_systeme_decide(self, monkeypatch) -> None:
        import greffier.interface.style as style

        monkeypatch.setattr(style, "system_is_dark", lambda: True)
        assert style.palette("systeme") is SOMBRE
        monkeypatch.setattr(style, "system_is_dark", lambda: False)
        assert style.palette("systeme") is CLAIR

    def test_une_valeur_inconnue_ne_fait_pas_tomber_la_fenetre(self, monkeypatch) -> None:
        """Un fichier écrit à la main peut porter n'importe quoi : on se rabat
        sur le système plutôt que de refuser de s'ouvrir."""
        import greffier.interface.style as style

        monkeypatch.setattr(style, "system_is_dark", lambda: False)
        assert style.palette("fluo") is CLAIR



class TestThemeDuSysteme:
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

    def test_macos_repond_dark(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Darwin")
        self._answer(monkeypatch, {"AppleInterfaceStyle": "Dark\n"})
        assert style.system_is_dark()

    def test_windows_lit_la_cle_a_l_envers(self, monkeypatch):
        """La clé dit si les applications sont en thème **clair** : 0 est sombre."""
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Windows")
        self._answer(monkeypatch, {
            "AppsUseLightTheme": "    AppsUseLightTheme    REG_DWORD    0x0\n"})
        assert style.system_is_dark()

    def test_windows_en_clair(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Windows")
        self._answer(monkeypatch, {
            "AppsUseLightTheme": "    AppsUseLightTheme    REG_DWORD    0x1\n"})
        assert not style.system_is_dark()

    def test_linux_par_le_portail_freedesktop(self, monkeypatch):
        """La clé portable, que GNOME comme KDE renseignent."""
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")
        self._answer(monkeypatch, {"freedesktop.portal": "(<<uint32 1>>,)\n"})
        assert style.system_is_dark()

    def test_linux_sans_portail_retombe_sur_gnome(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")
        self._answer(monkeypatch, {"gsettings": "'prefer-dark'\n"})
        assert style.system_is_dark()

    def test_un_systeme_muet_donne_le_theme_clair(self, monkeypatch):
        """Un repli clair est acceptable ; une fenêtre qui n'ouvre pas ne l'est pas."""
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")
        self._answer(monkeypatch, {})
        assert not style.system_is_dark()

    def test_une_commande_absente_ne_leve_pas(self, monkeypatch):
        from greffier.interface import style

        monkeypatch.setattr(style.platform, "system", lambda: "Linux")

        def absente(*_a, **_k):
            raise FileNotFoundError("gdbus")

        monkeypatch.setattr(style.subprocess, "run", absente)
        assert not style.system_is_dark()
