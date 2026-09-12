"""Tcl doit être trouvé même quand l'interpréteur porte un chemin de compilation.

La règle vit dans `emplacements.py`, avec les autres chemins, et non dans
`fenetre.py` : ce dernier importe Tk, qui ne démarre pas sur un exécuteur
d'intégration continue — la seule chose à tester serait alors intestable.
"""

from __future__ import annotations

from pathlib import Path

from greffier.locations import locate_tcl


def prefixe_avec_tcl(tmp_path: Path) -> Path:
    (tmp_path / "lib" / "tcl9.0").mkdir(parents=True)
    (tmp_path / "lib" / "tk9.0").mkdir()
    return tmp_path


class TestSituerTcl:
    def test_both_variables_are_set_beside_the_interpreter(self, tmp_path):
        env: dict[str, str] = {}
        locate_tcl(env, prefixe_avec_tcl(tmp_path))
        assert env["TCL_LIBRARY"] == str(tmp_path / "lib" / "tcl9.0")
        assert env["TK_LIBRARY"] == str(tmp_path / "lib" / "tk9.0")

    def test_a_setting_already_there_is_honoured(self, tmp_path):
        """Un poste qui a son propre Tcl garde le sien."""
        env = {"TCL_LIBRARY": "/usr/share/tcl9.0"}
        locate_tcl(env, prefixe_avec_tcl(tmp_path))
        assert env["TCL_LIBRARY"] == "/usr/share/tcl9.0"
        assert env["TK_LIBRARY"] == str(tmp_path / "lib" / "tk9.0")

    def test_with_no_tcl_folder_nothing_is_invented(self, tmp_path):
        """Sur une distribution où Tk vient du système, il n'y a rien à côté."""
        (tmp_path / "lib").mkdir()
        env: dict[str, str] = {}
        locate_tcl(env, tmp_path)
        assert env == {}

    def test_with_no_lib_folder_the_function_raises_nothing(self, tmp_path):
        env: dict[str, str] = {}
        locate_tcl(env, tmp_path / "absent")
        assert env == {}

    def test_the_most_recent_version_is_chosen(self, tmp_path):
        """Deux Tcl côte à côte : on prend le plus récent, pas le premier lu."""
        for version in ("8.6", "9.0"):
            (tmp_path / "lib" / f"tcl{version}").mkdir(parents=True)
            (tmp_path / "lib" / f"tk{version}").mkdir()
        env: dict[str, str] = {}
        locate_tcl(env, tmp_path)
        assert env["TCL_LIBRARY"].endswith("tcl9.0")
        assert env["TK_LIBRARY"].endswith("tk9.0")


class TestWhereADistributionKeepsTcl:
    """Debian and Ubuntu put init.tcl under share/tcltk, not under lib.

    The check looked in lib only, declared Tcl missing on a machine where Tcl
    finds its files perfectly well -- `set tcl_library` answers
    /usr/share/tcltk/tcl8.6 -- and the window refused to open on every
    distribution Python. Which is the interpreter the installer now prefers,
    for the antialiasing.
    """

    def _tcl_in(self, root, chemin):
        dossier = root / chemin
        dossier.mkdir(parents=True)
        (dossier / "init.tcl").write_text("", encoding="utf-8")

    def test_the_debian_layout_is_found(self, tmp_path, monkeypatch):
        from greffier.interface import startup

        self._tcl_in(tmp_path, "share/tcltk/tcl8.6")
        monkeypatch.setattr(startup.sys, "base_prefix", str(tmp_path))
        assert startup._default_tcl()

    def test_the_usual_layout_still_is(self, tmp_path, monkeypatch):
        from greffier.interface import startup

        self._tcl_in(tmp_path, "lib/tcl8.6")
        monkeypatch.setattr(startup.sys, "base_prefix", str(tmp_path))
        assert startup._default_tcl()

    def test_a_prefix_without_tcl_says_no(self, tmp_path, monkeypatch):
        from greffier.interface import startup

        (tmp_path / "lib").mkdir()
        monkeypatch.setattr(startup.sys, "base_prefix", str(tmp_path))
        monkeypatch.setattr(startup, "_OU_VIT_TCL", ("lib/tcl*",))
        assert not startup._default_tcl()
