"""A real window, built on a screen the test run owns, and nowhere else.

Tk needs a screen, and the only acceptable one is a screen this suite created:
running the tests on a desktop must never make windows appear in front of
somebody who is working. It happened once, and it is the reason for the
variable below. The continuous integration wraps the run in `xvfb-run` and sets
GREFFIER_ECRAN_D_ESSAI; without that variable these tests skip, whatever
DISPLAY happens to hold.
"""

from __future__ import annotations

import os

import pytest

OPT_IN = "GREFFIER_ECRAN_D_ESSAI"


@pytest.fixture
def window(tmp_path, monkeypatch):
    """The real window, painted once, closed at the end."""
    if not os.environ.get(OPT_IN):
        pytest.skip(
            f"aucun écran d'essai : pose {OPT_IN}=1 sous xvfb-run pour ces tests"
        )
    tk = pytest.importorskip("tkinter")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    for cle in [c for c in os.environ if c.startswith("GREFFIER_") and c != OPT_IN]:
        monkeypatch.delenv(cle)

    from greffier.adapters.configuration import Config
    from greffier.interface.window import Window

    try:
        ouverte = Window(Config())
    except tk.TclError as pourquoi:
        pytest.skip(f"pas d'écran pour Tk : {pourquoi}")
    ouverte.root.update()
    yield ouverte
    ouverte.root.destroy()
