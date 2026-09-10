"""Telling the user while the chain runs, with no terminal open."""

from __future__ import annotations

import platform
import shutil
import subprocess

SYSTEM = platform.system()

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
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
            " ContentType=WindowsRuntime] > $null"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, check=False,
        )
