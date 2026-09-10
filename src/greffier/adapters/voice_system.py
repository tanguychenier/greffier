"""Making the assistant speak, with the system's own voice.

The fallback: no model to download, and it works the moment the tool is
installed. It sounds like a machine, which is why the neural voice exists.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import threading

SYSTEM = platform.system()

QUALITES = ("Premium", "Enhanced")

COMPACTES_ACCEPTABLES = ("Thomas", "Amélie", "Audrey", "Aurelie")

DEBIT = 165

def _say_voice() -> list[tuple[str, str]]:
    """The French voices `say` knows, best first."""
    if SYSTEM != "Darwin" or shutil.which("say") is None:
        return []
    try:
        output = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    voice = []
    for line in output.splitlines():
        trouve = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if trouve and trouve.group(2).startswith("fr"):
            voice.append((trouve.group(1).strip(), trouve.group(2)))
    return voice

def best_voice() -> str | None:
    """The name of the best French voice installed."""
    voice = _say_voice()
    if not voice:
        return None
    for qualite in QUALITES:
        for language in ("fr_FR", "fr_CA"):
            for name, cette_langue in voice:
                if f"({qualite})" in name and cette_langue == language:
                    return name
    for prefere in COMPACTES_ACCEPTABLES:
        for name, _ in voice:
            if name.split(" (")[0] == prefere:
                return name
    return voice[0][0]

def better_voice_available() -> bool:
    """Is a neural voice installed?"""
    return any(
        f"({qualite})" in name for name, _ in _say_voice() for qualite in QUALITES
    )

class SystemVoice:
    """Pronounces a text through the system synthesiser."""

    def __init__(self, voice: str | None = None, debit: int = DEBIT) -> None:
        self.voice = voice if voice is not None else best_voice()
        self.debit = debit
        self._in_progress: subprocess.Popen[bytes] | None = None
        self._verrou = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self._command("essai"))

    def _command(self, text: str) -> list[str]:
        if SYSTEM == "Darwin" and shutil.which("say"):
            arguments = ["say", "-r", str(self.debit)]
            if self.voice:
                arguments += ["-v", self.voice]
            return [*arguments, text]
        if SYSTEM == "Linux":
            if shutil.which("spd-say"):
                return ["spd-say", "-l", "fr", "-w", text]
            if shutil.which("espeak-ng"):
                return ["espeak-ng", "-v", "fr", "-s", str(self.debit), text]
            return []
        if SYSTEM == "Windows" and shutil.which("powershell"):
            echappe = text.replace("'", "''")
            return [
                "powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Speech; "
                "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$v.Rate = {max(-10, min(10, (self.debit - 175) // 15))}; "
                f"$v.Speak('{echappe}')",
            ]
        return []

    def say(self, text: str) -> bool:
        """Starts the sentence and hands back. False when the system refuses."""
        remark = text.strip()
        if not remark:
            return False
        command = self._command(remark)
        if not command:
            return False
        self.go_quiet()
        with self._verrou:
            try:
                self._in_progress = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                return False
        return True

    def is_speaking(self) -> bool:
        with self._verrou:
            return self._in_progress is not None and self._in_progress.poll() is None

    def go_quiet(self) -> None:
        """Cuts the current sentence. No effect when there is none."""
        with self._verrou:
            in_progress, self._in_progress = self._in_progress, None
        if in_progress is not None and in_progress.poll() is None:
            in_progress.terminate()
            try:
                in_progress.wait(timeout=2)
            except subprocess.TimeoutExpired:
                in_progress.kill()

    def attendre(self, timeout: float = 30.0) -> None:
        """Waits for the sentence to finish. For the command line."""
        with self._verrou:
            in_progress = self._in_progress
        if in_progress is not None:
            try:
                in_progress.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.go_quiet()
