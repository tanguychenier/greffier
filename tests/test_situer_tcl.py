"""Tcl doit être trouvé même quand l'interpréteur porte un chemin de compilation.

La règle vit dans `emplacements.py`, avec les autres chemins, et non dans
`fenetre.py` : ce dernier importe Tk, qui ne démarre pas sur un exécuteur
d'intégration continue — la seule chose à tester serait alors intestable.
"""

from __future__ import annotations

from pathlib import Path

from greffier.emplacements import situer_tcl


def prefixe_avec_tcl(tmp_path: Path) -> Path:
    (tmp_path / "lib" / "tcl9.0").mkdir(parents=True)
    (tmp_path / "lib" / "tk9.0").mkdir()
    return tmp_path


class TestSituerTcl:
    def test_les_deux_variables_sont_posees_a_cote_de_l_interpreteur(self, tmp_path):
        env: dict[str, str] = {}
        situer_tcl(env, prefixe_avec_tcl(tmp_path))
        assert env["TCL_LIBRARY"] == str(tmp_path / "lib" / "tcl9.0")
        assert env["TK_LIBRARY"] == str(tmp_path / "lib" / "tk9.0")

    def test_un_reglage_deja_present_est_respecte(self, tmp_path):
        """Un poste qui a son propre Tcl garde le sien."""
        env = {"TCL_LIBRARY": "/usr/share/tcl9.0"}
        situer_tcl(env, prefixe_avec_tcl(tmp_path))
        assert env["TCL_LIBRARY"] == "/usr/share/tcl9.0"
        assert env["TK_LIBRARY"] == str(tmp_path / "lib" / "tk9.0")

    def test_sans_dossier_tcl_rien_n_est_invente(self, tmp_path):
        """Sur une distribution où Tk vient du système, il n'y a rien à côté."""
        (tmp_path / "lib").mkdir()
        env: dict[str, str] = {}
        situer_tcl(env, tmp_path)
        assert env == {}

    def test_sans_dossier_lib_la_fonction_ne_leve_rien(self, tmp_path):
        env: dict[str, str] = {}
        situer_tcl(env, tmp_path / "absent")
        assert env == {}

    def test_la_version_la_plus_recente_est_choisie(self, tmp_path):
        """Deux Tcl côte à côte : on prend le plus récent, pas le premier lu."""
        for version in ("8.6", "9.0"):
            (tmp_path / "lib" / f"tcl{version}").mkdir(parents=True)
            (tmp_path / "lib" / f"tk{version}").mkdir()
        env: dict[str, str] = {}
        situer_tcl(env, tmp_path)
        assert env["TCL_LIBRARY"].endswith("tcl9.0")
        assert env["TK_LIBRARY"].endswith("tk9.0")
