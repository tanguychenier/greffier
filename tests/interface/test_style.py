"""La palette et la typographie, éprouvées sans ouvrir de fenêtre.

Tk ne démarre pas sur un exécuteur d'intégration continue, et de toute façon
comparer des pixels ne dit rien d'utile. Ce qui se teste ici, c'est ce qui a
réellement cassé : une couleur invalide fait tomber Tk au dessin, et une palette
incomplète laisse un texte illisible sur son fond.
"""

from __future__ import annotations

import re

import pytest

from greffier.interface.style import CLAIR, SOMBRE, Palette, palette, police

TEINTE = re.compile(r"^#[0-9a-fA-F]{6}$")


def toutes(palette: Palette) -> dict[str, str]:
    return {
        nom: getattr(palette, nom)
        for nom in (
            "fond", "carte", "encre", "encre_pale", "filet", "accent",
            "accent_encre", "actif", "calme", "vert", "ambre", "survol",
        )
    }


class TestPalettes:
    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_chaque_couleur_est_une_teinte_valide(self, palette: Palette) -> None:
        # Une couleur mal écrite ne se voit pas à la lecture : elle fait tomber
        # Tk au premier dessin. C'est arrivé, avec des caractères non latins
        # glissés dans une valeur hexadécimale.
        for nom, valeur in toutes(palette).items():
            assert TEINTE.match(valeur), f"{nom} = {valeur!r}"

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_le_texte_contraste_avec_son_fond(self, palette: Palette) -> None:
        assert _contraste(palette.encre, palette.carte) >= 4.5
        assert _contraste(palette.encre, palette.fond) >= 4.5
        assert _contraste(palette.accent_encre, palette.accent) >= 4.5

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_le_texte_pale_reste_lisible(self, palette: Palette) -> None:
        # Assoupli à 3:1, la valeur admise pour du texte secondaire.
        assert _contraste(palette.encre_pale, palette.carte) >= 3.0

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_l_accent_est_une_vraie_teinte(self, palette: Palette) -> None:
        """Il valait le noir de l'encre : la fenêtre était entièrement grise et
        rien ne guidait l'œil. Un accent doit se distinguer de l'encre, se voir
        sur la carte, et ne pas se confondre avec un état."""
        assert palette.accent != palette.encre
        assert _contraste(palette.accent, palette.carte) >= 3.0
        for etat in (palette.actif, palette.vert, palette.ambre):
            assert palette.accent != etat

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_le_filet_se_voit(self, palette: Palette) -> None:
        """Mesuré à 1,28:1, il ne se voyait pas : bordures et séparateurs
        disparaissaient, et l'interface paraissait plate quoi qu'on fasse."""
        assert _contraste(palette.filet, palette.carte) >= 1.35
        assert _contraste(palette.filet, palette.fond) >= 1.3

    @pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
    def test_les_etats_se_distinguent(self, palette: Palette) -> None:
        # Rouge d'enregistrement, ambre de pause, gris de repos : trois états
        # qu'on doit pouvoir séparer d'un coup d'œil.
        etats = {palette.actif, palette.ambre, palette.calme}
        assert len(etats) == 3

    def test_les_deux_palettes_couvrent_les_memes_roles(self) -> None:
        assert toutes(CLAIR).keys() == toutes(SOMBRE).keys()

    def test_le_clair_et_le_sombre_sont_bien_inverses(self) -> None:
        assert _luminance(CLAIR.fond) > _luminance(CLAIR.encre)
        assert _luminance(SOMBRE.fond) < _luminance(SOMBRE.encre)


class TestPolice:
    def test_la_taille_est_respectee(self) -> None:
        assert police(13)[1] == 13

    def test_le_gras_se_demande(self) -> None:
        assert police(12, gras=True)[2] == "bold"
        assert police(12)[2] == "normal"

    def test_une_famille_est_toujours_donnee(self) -> None:
        # Sans famille, Tk retombe sur une police à empattements et l'interface
        # change d'allure d'un système à l'autre.
        assert police(12)[0]


def _luminance(teinte: str) -> float:
    """Luminance relative, telle que la définissent les règles d'accessibilité."""
    canaux = [int(teinte[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lineaires = [
        canal / 12.92 if canal <= 0.04045 else ((canal + 0.055) / 1.055) ** 2.4
        for canal in canaux
    ]
    return 0.2126 * lineaires[0] + 0.7152 * lineaires[1] + 0.0722 * lineaires[2]


def _contraste(premier: str, second: str) -> float:
    a, b = _luminance(premier), _luminance(second)
    clair, sombre = max(a, b), min(a, b)
    return (clair + 0.05) / (sombre + 0.05)


class TestChoixDuTheme:
    """Le thème est un réglage, plus seulement une lecture du système."""

    def test_un_theme_demande_est_rendu_tel_quel(self) -> None:
        assert palette("clair") is CLAIR
        assert palette("sombre") is SOMBRE

    def test_sans_demande_le_systeme_decide(self, monkeypatch) -> None:
        import greffier.interface.style as style

        monkeypatch.setattr(style, "systeme_en_sombre", lambda: True)
        assert style.palette("systeme") is SOMBRE
        monkeypatch.setattr(style, "systeme_en_sombre", lambda: False)
        assert style.palette("systeme") is CLAIR

    def test_une_valeur_inconnue_ne_fait_pas_tomber_la_fenetre(self, monkeypatch) -> None:
        """Un fichier écrit à la main peut porter n'importe quoi : on se rabat
        sur le système plutôt que de refuser de s'ouvrir."""
        import greffier.interface.style as style

        monkeypatch.setattr(style, "systeme_en_sombre", lambda: False)
        assert style.palette("fluo") is CLAIR

