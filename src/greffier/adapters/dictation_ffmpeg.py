"""Recording a sentence spoken to the assistant, and nothing more.

Not the meeting recorder. That one runs for hours, cuts its take into pieces and
survives a headset unplugged mid-sentence; this one takes a few seconds of one
person talking to a machine, and its only difficulty is stopping cleanly enough
that the last word is in the file.

**Held, never listening.** Outside a meeting a microphone that opens by itself
is a surveillance device, and no convenience is worth that. Pressing is the
decision; releasing is the end of the sentence, which also spares us guessing
where a silence means « I have finished ».
"""

from __future__ import annotations

import platform
import signal
import subprocess
import time
from pathlib import Path

SYSTEM = platform.system()

#: A sentence, not a speech. Past this the recording stops on its own: a key
#: held down by a book on a desk must not fill a disk.
SECONDES_MAXIMUM = 120


def _entree(device: str) -> list[str]:
    """The input, according to the system."""
    if SYSTEM == "Darwin":
        return ["-f", "avfoundation", "-i", f":{device or 'default'}"]
    if SYSTEM == "Windows":
        return ["-f", "dshow", "-i", f"audio={device or 'default'}"]
    return ["-f", "pulse", "-i", device or "default"]


class Dictation:
    """One sentence, from the press to the release."""

    def __init__(self, device: str = "", maximum: int = SECONDES_MAXIMUM) -> None:
        self.device = device
        self.maximum = maximum
        self._process: subprocess.Popen[bytes] | None = None
        self._file: Path | None = None

    @property
    def recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, destination: Path) -> None:
        """Opens the microphone. Refuses to open a second one."""
        if self.recording:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._file = destination
        self._process = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             *_entree(self.device),
             "-t", str(self.maximum),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(destination)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def stop(self) -> Path | None:
        """Closes it and hands back the file, or None when nothing was said.

        SIGINT and not SIGKILL, for the same reason as the meeting recorder: a
        wav whose header was never written is not a sentence, it is a file.
        """
        process, file = self._process, self._file
        self._process, self._file = None, None
        if process is None or file is None:
            return None
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            for _ in range(40):
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            else:
                process.kill()
        # A file of a few dozen bytes is a header and no sound: the key was
        # tapped rather than held, and there is nothing to transcribe.
        if not file.exists() or file.stat().st_size < 2_000:
            return None
        return file
