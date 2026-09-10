"""Prévenir l'utilisateur pendant que la chaîne tourne.

Le traitement d'une heure de réunion prend plusieurs minutes : personne ne reste
devant son terminal. Une notification du système est le seul moyen d'apprendre
que c'est prêt — ou que ça a échoué.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

SYSTEM = platform.system()

class NotificateurSysteme:
    """Trois implémentations derrière une seule méthode, choisie au démarrage."""

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
