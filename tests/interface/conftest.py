"""A real window, built on a screen the test run owns, and nowhere else.

Tk needs a screen, and the only acceptable one is a screen this suite created:
running the tests on a desktop must never make windows appear in front of
somebody who is working. It happened once, and it is the reason for the
variable below. The continuous integration wraps the run in `xvfb-run` and sets
GREFFIER_ECRAN_D_ESSAI; without that variable these tests skip, whatever
DISPLAY happens to hold.

The same variable also keeps the modal boxes shut, `interface/asking.py`
reading it: a box put to nobody waits for an answer that never comes, and that
is what hung the window proof for as long as this fixture went unused.
"""

from __future__ import annotations

import os

import pytest

OPT_IN = "GREFFIER_ECRAN_D_ESSAI"


@pytest.fixture
def test_screen(tmp_path, monkeypatch):
    """A screen of our own, and a machine with nothing configured on it.

    Returns nothing: it is the ground every window test stands on. Taking it
    without the window fixture is what lets a test watch the construction
    itself, rather than a window already built and painted.
    """
    if not os.environ.get(OPT_IN):
        pytest.skip(
            f"aucun écran d'essai : pose {OPT_IN}=1 sous xvfb-run pour ces tests"
        )
    pytest.importorskip("tkinter")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    for the_key in [c for c in os.environ if c.startswith("GREFFIER_") and c != OPT_IN]:
        monkeypatch.delenv(the_key)

    from greffier.interface import asking

    asking.forget_what_was_asked()
    yield
    asking.forget_what_was_asked()


@pytest.fixture
def window(test_screen):
    """The real window, painted once, closed at the end."""
    import tkinter as tk

    from greffier.adapters.configuration import Config
    from greffier.interface.window import Window

    try:
        opened_one = Window(Config())
    except tk.TclError as why:
        pytest.skip(f"pas d'écran pour Tk : {why}")
    opened_one.root.update()
    yield opened_one
    opened_one.root.destroy()
