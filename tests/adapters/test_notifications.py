"""The notifier tells the system what it was told, and swallows its refusals.

The Windows branch used to load the WinRT type and stop there: the title and the
message never left the process, and no toast was ever shown.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from greffier.adapters import notifications
from greffier.adapters.notifications import SystemNotifier

TITLE = "Greffier"
MESSAGE = "Compte rendu prêt : réunion du 3 octobre"

#: The value of CREATE_NO_WINDOW in the Windows API. `subprocess` defines it on
#: Windows only, and these tests run elsewhere.
CREATE_NO_WINDOW = 0x08000000


@pytest.fixture
def launched(monkeypatch):
    """Catches what would have been run, with its options, and runs nothing."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class Done:
        returncode = 0

    def record(arguments, **options):
        calls.append((arguments, options))
        return Done()

    monkeypatch.setattr(notifications.subprocess, "run", record)
    return calls


def on(monkeypatch, system: str) -> None:
    monkeypatch.setattr(notifications, "SYSTEM", system)


def the_script(arguments: list[str]) -> str:
    return arguments[arguments.index("-Command") + 1]


class TestOnWindows:
    """A toast with its two lines, and not a byte of user text inside the script."""

    def test_powershell_is_what_runs(self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, _options),) = launched
        assert arguments[0] == "powershell"
        assert "-NoProfile" in arguments

    def test_powershell_opens_no_console_of_its_own(self, monkeypatch, launched):
        """Built `--windowed`, the application has no console. A console child is
        given one by Windows, and the toast would come after a black window."""
        on(monkeypatch, "Windows")
        monkeypatch.setattr(
            notifications.subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW, raising=False)
        SystemNotifier().notify(TITLE, MESSAGE)
        ((_arguments, options),) = launched
        assert options["creationflags"] == CREATE_NO_WINDOW

    def test_without_the_flag_in_subprocess_no_flag_is_asked(self, monkeypatch, launched):
        """Elsewhere than on Windows `subprocess` has no CREATE_NO_WINDOW."""
        on(monkeypatch, "Windows")
        monkeypatch.delattr(notifications.subprocess, "CREATE_NO_WINDOW", raising=False)
        SystemNotifier().notify(TITLE, MESSAGE)
        ((_arguments, options),) = launched
        assert options["creationflags"] == 0

    def test_the_title_and_the_message_travel_through_the_environment(
            self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((_arguments, options),) = launched
        assert options["env"]["GREFFIER_TITRE"] == TITLE
        assert options["env"]["GREFFIER_MSG"] == MESSAGE

    def test_the_script_reads_both_variables(self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, _options),) = launched
        assert "$env:GREFFIER_TITRE" in the_script(arguments)
        assert "$env:GREFFIER_MSG" in the_script(arguments)

    def test_no_user_text_reaches_the_script(self, monkeypatch, launched):
        """A message is data; a message able to close a quote would be code."""
        on(monkeypatch, "Windows")
        hostile = "'); Remove-Item -Recurse $env:USERPROFILE #"
        SystemNotifier().notify(hostile, hostile)
        ((arguments, _options),) = launched
        assert hostile not in the_script(arguments)
        assert "Remove-Item" not in the_script(arguments)

    def test_the_two_line_template_is_filled_through_the_dom(self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, _options),) = launched
        script = the_script(arguments)
        assert "ToastText02" in script
        assert "Windows.Data.Xml.Dom" in script
        assert script.count("CreateTextNode") == 2, "one text node per line of the template"
        assert "<text" not in script, "no XML assembled by hand"

    def test_the_toast_is_shown_on_behalf_of_powershell(self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, _options),) = launched
        script = the_script(arguments)
        assert (
            "CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
            "\\WindowsPowerShell\\v1.0\\powershell.exe')" in script
        )
        assert ".Show($toast)" in script

    def test_powershell_is_given_the_system_root_of_this_machine(
            self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        monkeypatch.setenv("SYSTEMROOT", "D:\\Fenetres")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((_arguments, options),) = launched
        assert options["env"]["SystemRoot"] == "D:\\Fenetres"

    def test_without_a_system_root_around_the_usual_one_is_assumed(
            self, monkeypatch, launched):
        on(monkeypatch, "Windows")
        monkeypatch.delenv("SYSTEMROOT", raising=False)
        SystemNotifier().notify(TITLE, MESSAGE)
        ((_arguments, options),) = launched
        assert options["env"]["SystemRoot"] == "C:\\Windows"

    def test_the_environment_carries_nothing_else(self, monkeypatch, launched):
        """The rest of our environment is nobody's business, PowerShell's included."""
        on(monkeypatch, "Windows")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((_arguments, options),) = launched
        assert set(options["env"]) == {"GREFFIER_TITRE", "GREFFIER_MSG", "SystemRoot"}


class TestOnMacOS:
    def test_osascript_receives_the_texts_through_the_environment(
            self, monkeypatch, launched):
        on(monkeypatch, "Darwin")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, options),) = launched
        assert arguments[0] == "osascript"
        assert options["env"]["GREFFIER_TITRE"] == TITLE
        assert options["env"]["GREFFIER_MSG"] == MESSAGE

    def test_the_applescript_holds_no_user_text(self, monkeypatch, launched):
        on(monkeypatch, "Darwin")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, _options),) = launched
        applescript = arguments[arguments.index("-e") + 1]
        assert TITLE not in applescript and MESSAGE not in applescript
        assert "GREFFIER_TITRE" in applescript and "GREFFIER_MSG" in applescript


class TestOnLinux:
    def test_notify_send_carries_the_texts_when_it_is_there(self, monkeypatch, launched):
        on(monkeypatch, "Linux")
        monkeypatch.setattr(notifications.shutil, "which", lambda _name: "/usr/bin/notify-send")
        SystemNotifier().notify(TITLE, MESSAGE)
        ((arguments, _options),) = launched
        assert arguments == ["notify-send", TITLE, MESSAGE]

    def test_nothing_runs_without_notify_send(self, monkeypatch, launched):
        on(monkeypatch, "Linux")
        monkeypatch.setattr(notifications.shutil, "which", lambda _name: None)
        SystemNotifier().notify(TITLE, MESSAGE)
        assert launched == []


class TestWhenTheSystemRefuses:
    """A notification that brought the chain down would be a very poor trade."""

    def refusing(self, monkeypatch, trouble: Exception) -> None:
        def refuse(*_arguments, **_options):
            raise trouble

        monkeypatch.setattr(notifications.subprocess, "run", refuse)

    @pytest.mark.parametrize("system", ["Darwin", "Windows"])
    def test_a_missing_program_is_swallowed(self, monkeypatch, system):
        on(monkeypatch, system)
        self.refusing(monkeypatch, FileNotFoundError("absent"))
        assert SystemNotifier().notify(TITLE, MESSAGE) is None

    def test_a_subprocess_failure_is_swallowed(self, monkeypatch):
        on(monkeypatch, "Darwin")
        self.refusing(monkeypatch, subprocess.TimeoutExpired("osascript", 1.0))
        assert SystemNotifier().notify(TITLE, MESSAGE) is None

    def test_an_unknown_system_launches_nothing(self, monkeypatch, launched):
        on(monkeypatch, "Haiku")
        SystemNotifier().notify(TITLE, MESSAGE)
        assert launched == []
