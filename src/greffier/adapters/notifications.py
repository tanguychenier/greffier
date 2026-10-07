"""Telling the user while the chain runs, with no terminal open."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

SYSTEM = platform.system()

#: The AppUserModelId of Windows PowerShell. A toast is shown on behalf of a
#: registered application and a script has none of its own: borrowing the
#: shell's is the idiom that makes `Show` display something.
_POWERSHELL_APP_ID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
)

#: Fills the two lines of the ToastText02 template. The texts come from the
#: environment and go in through the XML DOM, so nothing the user wrote is ever
#: interpolated into the script, nor into the XML.
_WINDOWS_TOAST = "; ".join((
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
    " ContentType=WindowsRuntime] > $null",
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument,"
    " ContentType=WindowsRuntime] > $null",
    "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02)",
    "$lines = $xml.GetElementsByTagName('text')",
    "$lines.Item(0).AppendChild($xml.CreateTextNode($env:GREFFIER_TITRE)) > $null",
    "$lines.Item(1).AppendChild($xml.CreateTextNode($env:GREFFIER_MSG)) > $null",
    "$toast = New-Object Windows.UI.Notifications.ToastNotification -ArgumentList $xml",
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    f"'{_POWERSHELL_APP_ID}').Show($toast)",
))

class SystemNotifier:
    """Three implementations behind one method, one per system."""

    def notify(self, title: str, message: str) -> None:
        try:
            if SYSTEM == "Darwin":
                self._macos(title, message)
            elif SYSTEM == "Linux":
                self._linux(title, message)
            elif SYSTEM == "Windows":
                self._windows(title, message)
        except (OSError, subprocess.SubprocessError):
            pass

    def _macos(self, title: str, message: str) -> None:
        subprocess.run(
            ["osascript", "-e",
             'display notification (system attribute "GREFFIER_MSG") '
             'with title (system attribute "GREFFIER_TITRE")'],
            env={"GREFFIER_TITRE": title, "GREFFIER_MSG": message,
                 "PATH": "/usr/bin:/bin"},
            capture_output=True, check=False,
        )

    def _linux(self, title: str, message: str) -> None:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, check=False)

    def _windows(self, title: str, message: str) -> None:
        """Shows a toast through Windows PowerShell.

        Written against the WinRT documentation and the PowerShell idiom, and not
        run on a Windows machine: like the Windows build itself, this branch awaits
        its first real screen. SystemRoot travels with the texts because the
        `subprocess` documentation warns that a Windows child without a valid one
        cannot load a side-by-side assembly, and PowerShell is such a program.
        CREATE_NO_WINDOW is there because the executable is built `--windowed`:
        a console program started from a parent without a console is given one of
        its own, so every toast would flash a black window first. The flag exists
        only in the Windows `subprocess`, hence `getattr`; this too awaits Windows.
        """
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", _WINDOWS_TOAST],
            env={"GREFFIER_TITRE": title, "GREFFIER_MSG": message,
                 "SystemRoot": os.environ.get("SYSTEMROOT", "C:\\Windows")},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, check=False,
        )
