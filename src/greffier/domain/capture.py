"""Deciding whether capture is still advancing, mid-meeting.

A recording that stops growing has to be said **during** the meeting: found out
afterwards, there is nothing left to record.
"""

from __future__ import annotations

from dataclasses import dataclass

TURNS_BEFORE_ALERT = 3

@dataclass
class CaptureWatch:
    """Follows the size of the current file and says when capture stopped."""

    still_turns: int = 0
    alertee: bool = False
    _taille: int | None = None

    def observe(self, bytes_read: int) -> str:
        """What needs reporting, or an empty string when nothing does."""
        precedente, self._taille = self._taille, bytes_read
        if precedente is None:
            return ""
        if bytes_read > precedente:
            self.still_turns = 0
            self.alertee = False
            return ""

        self.still_turns += 1
        if self.still_turns < TURNS_BEFORE_ALERT or self.alertee:
            return ""
        self.alertee = True
        return (
            "L'enregistrement n'avance plus : aucun son n'a été écrit depuis "
            f"{self.still_turns * 4} secondes. Vérifie le micro et "
            "l'autorisation d'accès, puis relance la réunion."
        )
