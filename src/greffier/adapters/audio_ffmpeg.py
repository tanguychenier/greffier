"""Recording and measuring sound, through ffmpeg."""

from __future__ import annotations

import platform
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

SYSTEM = platform.system()

SILENCE_NUMERIQUE = -120.0

_LEVEL = re.compile(r"RMS level dB: (-?[\d.]+|-inf)")

class FfmpegRecorder:
    def __init__(self, peripherique: str, maximum_length: int = 14_400) -> None:
        self.peripherique = peripherique
        self.maximum_length = maximum_length

    def _input(self) -> list[str]:
        if SYSTEM == "Darwin":
            return ["-f", "avfoundation", "-i", f":{self._avfoundation_index()}"]
        if SYSTEM == "Linux":
            return ["-f", "pulse", "-i", self.peripherique]
        return ["-f", "dshow", "-i", f"audio={self.peripherique}"]

    def _index_of(self, peripherique: str) -> str:
        """The avfoundation index of a named input."""
        output = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False,
        ).stderr
        audio = output.split("AVFoundation audio devices")[-1]
        for line in audio.splitlines():
            found = re.search(r"\[(\d+)\] (.+)$", line)
            if found and found.group(2).strip() == peripherique:
                return found.group(1)
        raise RuntimeError(f"Périphérique « {peripherique} » introuvable.")

    def _avfoundation_index(self) -> str:
        """The device's index in avfoundation's list."""
        output = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False,
        ).stderr
        audio = output.split("AVFoundation audio devices")[-1]
        for line in audio.splitlines():
            found = re.search(r"\[(\d+)\] (.+)$", line)
            if found and found.group(2).strip() == self.peripherique:
                return found.group(1)
        raise RuntimeError(
            f"Périphérique « {self.peripherique} » introuvable. "
            "Crée-le dans Configuration audio et MIDI, ou change « audio.entree »."
        )

    def start_recording(self, destination: Path) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        processus = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             *self._input(), "-t", str(self.maximum_length),
             "-ar", "16000", "-c:a", "pcm_s16le", str(destination)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return processus.pid

    def stop_recording(self, processus: int) -> None:
        """Stops with SIGINT, never with SIGKILL.

        SIGKILL leaves the file's header unwritten, and a wav without a header is an
        unreadable meeting.
        """
        import os
        import time

        try:
            os.kill(processus, signal.SIGINT)
        except ProcessLookupError:
            return
        for _ in range(60):
            time.sleep(0.25)
            try:
                os.kill(processus, 0)
            except ProcessLookupError:
                return
        os.kill(processus, signal.SIGKILL)

    def prepare_transcript(self, audio: Path, destination: Path) -> Path:
        """Normalises each channel, then mixes them."""
        channels = self._channels(audio) or 1
        if channels == 1:
            filtre = "loudnorm=I=-20:TP=-1.5:LRA=11"
        else:
            parts = "".join(
                f"[0:a]pan=mono|c0=c{i},loudnorm=I=-20:TP=-1.5:LRA=11[c{i}];"
                for i in range(channels)
            )
            entrees = "".join(f"[c{i}]" for i in range(channels))
            filtre = f"{parts}{entrees}amix=inputs={channels}:normalize=0,loudnorm=I=-20:TP=-1.5"
        destination.parent.mkdir(parents=True, exist_ok=True)
        drapeau = "-filter_complex" if channels > 1 else "-af"
        done = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
             drapeau, filtre, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             str(destination)],
            capture_output=True, text=True, check=False,
        )
        if done.returncode != 0 or not destination.exists():
            return audio
        return destination

    def wire_up(self, chunks: list[Path], destination: Path) -> Path:
        """Stitches the chunks, making the channel counts uniform."""
        present_line = [m for m in chunks if m.exists() and m.stat().st_size > 0]
        if not present_line:
            raise RuntimeError("aucun morceau exploitable à recoller")
        if len(present_line) == 1:
            if present_line[0] != destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                present_line[0].replace(destination)
            return destination

        channels = min((self._channels(m) for m in present_line), default=1) or 1
        with tempfile.TemporaryDirectory() as folder:
            atelier = Path(folder)
            uniformes: list[Path] = []
            for rank, morceau in enumerate(present_line):
                if self._channels(morceau) == channels:
                    uniformes.append(morceau)
                    continue
                converti = atelier / f"{rank:02d}.wav"
                self._run_chain(
                    ["-i", str(morceau), "-ac", str(channels), "-ar", "16000",
                     "-c:a", "pcm_s16le", str(converti)],
                    "conversion d'un morceau impossible",
                )
                uniformes.append(converti)

            listing = atelier / "morceaux.txt"
            listing.write_text(
                "".join(f"file '{m.resolve()}'\n" for m in uniformes), encoding="utf-8"
            )
            recolle = atelier / "recolle.wav"
            self._run_chain(
                ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(recolle)],
                "recollage impossible",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(recolle), str(destination))
        return destination

    def _run_chain(self, arguments: list[str], echec: str) -> None:
        done = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
            capture_output=True, text=True, check=False,
        )
        if done.returncode != 0:
            latest = (done.stderr or done.stdout).strip().splitlines()
            raise RuntimeError(echec + (f" : {latest[-1]}" if latest else ""))

    def _channels(self, audio: Path) -> int:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=channels", "-of", "csv=p=0", str(audio)],
            capture_output=True, text=True, check=False,
        )
        try:
            return int(done.stdout.strip().split(",")[0])
        except (ValueError, IndexError):
            return 0

    def try_it(self, peripherique: str, seconds: float = 1.5) -> float:
        """Listens briefly to an input and returns its level."""
        if SYSTEM != "Darwin":
            return 0.0
        try:
            index = self._index_of(peripherique)
        except RuntimeError:
            return SILENCE_NUMERIQUE
        with tempfile.TemporaryDirectory() as folder:
            essai = Path(folder) / "essai.wav"
            done = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "avfoundation", "-i", f":{index}", "-t", f"{seconds}",
                 "-ar", "16000", str(essai)],
                capture_output=True, text=True, check=False,
            )
            if done.returncode != 0 or not essai.exists():
                return SILENCE_NUMERIQUE
            mesures = self.levels(essai)
        return max(mesures) if mesures else SILENCE_NUMERIQUE

    def levels(self, audio: Path) -> list[float]:
        """RMS level of each channel, in dB."""
        output = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(audio),
             "-af", "astats=measure_overall=none:measure_perchannel=RMS_level",
             "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        ).stderr
        mesures = []
        for value in _LEVEL.findall(output):
            mesures.append(
                SILENCE_NUMERIQUE if value == "-inf"
                else max(float(value), SILENCE_NUMERIQUE)
            )
        return mesures
