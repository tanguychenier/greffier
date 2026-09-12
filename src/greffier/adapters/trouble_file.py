"""The incident file: one line each, the newest last.

A plain text file rather than a database or a service: somebody who reports a
problem has to be able to open it, read it, and decide to attach it. Nothing
leaves the machine on its own.
"""

from __future__ import annotations

import contextlib
import platform
from pathlib import Path

from greffier.domain.trouble import Trouble, worth_keeping

KEPT = 200

class TroubleFile:
    """Files what went wrong, and never raises while doing it."""

    def __init__(self, file: Path, version: str = "") -> None:
        self.file = Path(file)
        self.version = version
        self.system = f"{platform.system()} {platform.machine()}"

    def note(self, where: str, what: str) -> None:
        """Writes one incident down. A failure here must cost nothing."""
        with contextlib.suppress(OSError, ValueError):
            ligne = Trouble(where=where, what=what).line(self.version, self.system)
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with self.file.open("a", encoding="utf-8") as journal:
                journal.write(ligne + "\n")
            self._hold_it_down()

    def read(self, how_many: int = 40) -> list[str]:
        """The last incidents, newest last. Empty when there is no file."""
        with contextlib.suppress(OSError):
            lignes = self.file.read_text(encoding="utf-8").splitlines()
            return worth_keeping(lignes, how_many)
        return []

    def _hold_it_down(self) -> None:
        """Keeps the file to its last lines: it is read by a person."""
        with contextlib.suppress(OSError):
            lignes = self.file.read_text(encoding="utf-8").splitlines()
            if len(lignes) <= KEPT * 2:
                return
            self.file.write_text(
                "\n".join(worth_keeping(lignes, KEPT)) + "\n", encoding="utf-8")
