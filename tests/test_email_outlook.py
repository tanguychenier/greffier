"""The sending probe: knowing at the start of a meeting whether the minutes will go.

The defect, seen on 2026-09-10: the sending of a meeting of one hour forty-two
failed at 12:17 in front of a locked screen, two hours after the moment when
somebody was at the keyboard and one click would have been enough. macOS asks
for an automation permission the first time, and its dialogue does not always
appear when the run is detached.

No `osascript` is launched here: the subprocess is what gets replaced, which
makes every AppleScript error code coverable with neither Outlook nor macOS.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from greffier.adapters.email import OutlookSender


class Output:
    def __init__(self, returncode: int, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def _answer(monkeypatch: pytest.MonkeyPatch, output: Any) -> list[list[str]]:
    appels: list[list[str]] = []

    def faux_run(command: list[str], **_options: Any) -> Any:
        appels.append(command)
        if isinstance(output, Exception):
            raise output
        return output

    monkeypatch.setattr(subprocess, "run", faux_run)
    return appels


class TestSondeDEnvoi:
    def test_a_clear_path_says_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _answer(monkeypatch, Output(0, stdout="Microsoft Outlook"))
        assert OutlookSender().probe() is None

    def test_the_probe_sends_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It asks Outlook for its name, and nothing more."""
        appels = _answer(monkeypatch, Output(0))
        OutlookSender().probe()
        script = " ".join(appels[0])
        assert "get name" in script
        assert "send" not in script
        assert "outgoing message" not in script

    def test_a_missing_permission_says_where_to_click(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A message that does not say what to do makes it look like all is lost."""
        _answer(monkeypatch, Output(1, stderr="execution error: ... (-1743)"))
        empeche = OutlookSender().probe()
        assert empeche is not None
        assert "Automatisation" in empeche
        assert "ne partira pas" in empeche

    def test_outlook_closed_is_said_differently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _answer(monkeypatch, Output(1, stderr="Application isn't running (-1728)"))
        empeche = OutlookSender().probe()
        assert empeche is not None
        assert "lancé" in empeche

    def test_an_unknown_error_is_reported_as_it_is(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _answer(monkeypatch, Output(1, stderr="quelque chose d'inédit"))
        empeche = OutlookSender().probe()
        assert empeche is not None
        assert "inédit" in empeche

    def test_a_probe_that_never_ends_does_not_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It is called when a meeting starts: it has to return."""
        _answer(monkeypatch, subprocess.TimeoutExpired(cmd="osascript", timeout=20))
        assert OutlookSender().probe() == "Outlook ne répond pas."

    def test_a_missing_osascript_reports_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _answer(monkeypatch, FileNotFoundError("osascript"))
        assert OutlookSender().probe() == "Outlook ne répond pas."


class TestWhenOutlookDoesNotAnswer:
    """AppleScript's codes have to become sentences a person can act on.

    The minutes of the meeting of 2026-09-10 never left, and the conversation
    carried this: "Envoi impossible : ['297:373: execution error: Erreur dans
    Microsoft Outlook : Délai dépassé pour un AppleEvent. (-1712)']". An error code
    and a line number tell nobody what to do.

    The cause is fixed upstream, the send order now being wrapped in a "with
    timeout of 600 seconds" where AppleScript gives up after sixty by default, but
    a timeout can still happen, and it has to say so.
    """

    def _envoyer(self, monkeypatch, output: str, code: int = 1):
        appels: list[list[str]] = []

        class Returned:
            returncode = code
            stderr = output
            stdout = ""

        def faux_run(commande, **_options):
            appels.append(commande)
            return Returned()

        monkeypatch.setattr(subprocess, "run", faux_run)
        OutlookSender().send("moi@exemple.fr", "Sujet", "Corps", [])

    def test_a_timeout_says_what_to_do(self, monkeypatch):
        with pytest.raises(TimeoutError) as souci:
            self._envoyer(monkeypatch, "execution error: ... (-1712)")
        said = str(souci.value)
        assert "n'a pas répondu à temps" in said
        assert "greffier envoyer" in said, "il faut dire comment réessayer"

    def test_outlook_closed_is_said_differently(self, monkeypatch):
        with pytest.raises(RuntimeError, match="n'est pas lancé"):
            self._envoyer(monkeypatch, "Application isn't running (-1728)")

    def test_l_autorisation_manquante_reste_distincte(self, monkeypatch):
        with pytest.raises(PermissionError, match="Automatisation"):
            self._envoyer(monkeypatch, "execution error: ... (-1743)")

    def test_an_unknown_error_keeps_the_last_line(self, monkeypatch):
        with pytest.raises(RuntimeError, match="quelque chose d'inédit"):
            self._envoyer(monkeypatch, "bruit\nquelque chose d'inédit")

    def test_a_sending_that_works_says_nothing(self, monkeypatch):
        self._envoyer(monkeypatch, "", code=0)

    def test_le_delai_entoure_l_ordre_d_envoi(self):
        """La cause : AppleScript abandonne au bout de soixante secondes."""
        source = OutlookSender.SOURCE
        assert "with timeout of 600 seconds" in source
        assert source.index("with timeout") < source.index("send m")
        assert "end timeout" in source

    def test_the_probe_has_its_own_timeout(self):
        """It runs when a meeting starts: it has to return."""
        assert "with timeout of 60 seconds" in OutlookSender.SONDE
