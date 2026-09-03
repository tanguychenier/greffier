"""Prévenir l'utilisateur pendant que la chaîne tourne.

Le traitement d'une heure de réunion prend plusieurs minutes : personne ne reste
devant son terminal. Une notification du système est le seul moyen d'apprendre
que c'est prêt — ou que ça a échoué.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

SYSTEME = platform.system()


class NotificateurSysteme:
    """Trois implémentations derrière une seule méthode, choisie au démarrage."""

    def notifier(self, titre: str, message: str) -> None:
        try:
            if SYSTEME == "Darwin":
                self._macos(titre, message)
            elif SYSTEME == "Linux":
                self._linux(titre, message)
            elif SYSTEME == "Windows":
                self._windows(titre, message)
        except (OSError, subprocess.SubprocessError):
            # Une notification qui échoue ne doit jamais faire échouer une
            # réunion : c'est un confort, pas un maillon de la chaîne.
            pass

    def _macos(self, titre: str, message: str) -> None:
        # Titre et message par l'environnement : une apostrophe dans un nom de
        # réunion casserait le script AppleScript.
        subprocess.run(
            ["osascript", "-e",
             'display notification (system attribute "GREFFIER_MSG") '
             'with title (system attribute "GREFFIER_TITRE")'],
            env={"GREFFIER_TITRE": titre, "GREFFIER_MSG": message,
                 "PATH": "/usr/bin:/bin"},
            capture_output=True, check=False,
        )

    def _linux(self, titre: str, message: str) -> None:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", titre, message], capture_output=True, check=False)

    def _windows(self, titre: str, message: str) -> None:
        # PowerShell est le seul moyen d'afficher une notification sans rien
        # installer sur un poste Windows.
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
            " ContentType=WindowsRuntime] > $null"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, check=False,
        )
