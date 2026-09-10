"""Reads the real audio hardware, so the watch is not guessing."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path

from greffier.domain.devices import Device, Hardware

SYSTEM = platform.system()

_LINE = re.compile(r"^\s{2}(\S.*?)\s+\[(.+?)\]\s*$")
_UID = re.compile(r"^\s+uid:\s*(.+?)\s*$")
_ENTREES = re.compile(r"entrée (\d+)ch")
_SORTIES = re.compile(r"sortie (\d+)ch")

class CoreAudioLister:
    """Gives the state of the audio hardware, on demand."""

    def __init__(self, source: Path, cache: Path, prete: Path | None = None) -> None:
        self.source = source
        self.prete = prete
        self.binaire = cache / "lister-peripheriques"

    def available(self) -> bool:
        if SYSTEM != "Darwin":
            return False
        return self.source.exists() or (self.prete is not None and self.prete.exists())

    def _compiler(self) -> bool:
        """Compile la source si besoin. Faux si la compilation est impossible."""
        if self.binaire.exists() and self.binaire.stat().st_mtime >= self.source.stat().st_mtime:
            return True
        if not shutil.which("swiftc"):
            return False
        self.binaire.parent.mkdir(parents=True, exist_ok=True)
        fait = subprocess.run(
            ["swiftc", "-O", str(self.source), "-o", str(self.binaire)],
            capture_output=True, text=True, check=False,
        )
        return fait.returncode == 0 and self.binaire.exists()

    def _raw_output(self) -> str:
        if self.prete is not None and self.prete.exists():
            command = [str(self.prete), "--list"]
        elif self._compiler():
            command = [str(self.binaire), "--list"]
        elif shutil.which("swift"):
            command = ["swift", str(self.source), "--list"]
        else:
            return ""
        fait = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        return fait.stdout

    def read(self) -> Hardware:
        """The hardware state now. Empty when the system will not say."""
        if not self.available():
            return Hardware()
        try:
            return analyser(self._raw_output())
        except (subprocess.SubprocessError, OSError):
            return Hardware()

def analyser(output: str) -> Hardware:
    """Turns the lister's output into hardware the domain understands."""
    trouves: list[Device] = []
    in_progress: tuple[str, str] | None = None
    for line in output.splitlines():
        header = _LINE.match(line)
        if header:
            in_progress = (header.group(1), header.group(2))
            continue
        uid = _UID.match(line)
        if uid and in_progress is not None:
            name, channels = in_progress
            entrees = _ENTREES.search(channels)
            sorties = _SORTIES.search(channels)
            trouves.append(
                Device(
                    name=name,
                    uid=uid.group(1),
                    entrees=int(entrees.group(1)) if entrees else 0,
                    sorties=int(sorties.group(1)) if sorties else 0,
                )
            )
            in_progress = None
    return Hardware(tuple(trouves))
