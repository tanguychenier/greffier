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

DIGITAL_SILENCE = -120.0

_LEVEL = re.compile(r"RMS level dB: (-?[\d.]+|-inf)")

#: What may stand in for the microphone.
REPLAYABLE = frozenset({".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".mp4", ".mkv", ".webm"})


class FfmpegRecorder:
    def __init__(self, device: str, maximum_length: int = 14_400) -> None:
        self.device = device
        self.maximum_length = maximum_length

    def _input(self) -> list[str]:
        # A file in place of a device: the recording is played at its own
        # pace, and everything downstream (the chunks, the watch, the live
        # thread, the assistant) sees exactly what a microphone would have
        # given. It is how a meeting is replayed without holding one.
        if self.replays_a_file():
            return ["-re", "-i", self.device]
        if SYSTEM == "Darwin":
            return ["-f", "avfoundation", "-i", f":{self._avfoundation_index()}"]
        if SYSTEM == "Linux":
            return ["-f", "pulse", "-i", self.device]
        return ["-f", "dshow", "-i", f"audio={self.device}"]

    def replays_a_file(self) -> bool:
        """Whether the input names a recording rather than a device."""
        return Path(self.device).suffix.lower() in REPLAYABLE and Path(self.device).is_file()

    def _index_of(self, device: str) -> str:
        """The avfoundation index of a named input."""
        output = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False,
        ).stderr
        audio = output.split("AVFoundation audio devices")[-1]
        for line in audio.splitlines():
            found = re.search(r"\[(\d+)\] (.+)$", line)
            if found and found.group(2).strip() == device:
                return found.group(1)
        raise RuntimeError(f"Périphérique « {device} » introuvable.")

    def _avfoundation_index(self) -> str:
        """The device's index in avfoundation's list."""
        output = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False,
        ).stderr
        audio = output.split("AVFoundation audio devices")[-1]
        for line in audio.splitlines():
            found = re.search(r"\[(\d+)\] (.+)$", line)
            if found and found.group(2).strip() == self.device:
                return found.group(1)
        raise RuntimeError(
            f"Périphérique « {self.device} » introuvable. "
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
            for rank, chunk in enumerate(present_line):
                if self._channels(chunk) == channels:
                    uniformes.append(chunk)
                    continue
                converti = atelier / f"{rank:02d}.wav"
                self._run_chain(
                    ["-i", str(chunk), "-ac", str(channels), "-ar", "16000",
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

    def try_it(self, device: str, seconds: float = 1.5) -> float:
        """Listens briefly to an input and returns its level."""
        if SYSTEM != "Darwin":
            return 0.0
        try:
            index = self._index_of(device)
        except RuntimeError:
            return DIGITAL_SILENCE
        with tempfile.TemporaryDirectory() as folder:
            essai = Path(folder) / "essai.wav"
            done = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "avfoundation", "-i", f":{index}", "-t", f"{seconds}",
                 "-ar", "16000", str(essai)],
                capture_output=True, text=True, check=False,
            )
            if done.returncode != 0 or not essai.exists():
                return DIGITAL_SILENCE
            measures = self.levels(essai)
        return max(measures) if measures else DIGITAL_SILENCE

    def levels(self, audio: Path) -> list[float]:
        """RMS level of each channel, in dB."""
        output = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(audio),
             "-af", "astats=measure_overall=none:measure_perchannel=RMS_level",
             "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        ).stderr
        measures = []
        for value in _LEVEL.findall(output):
            measures.append(
                DIGITAL_SILENCE if value == "-inf"
                else max(float(value), DIGITAL_SILENCE)
            )
        return measures

def why_unreadable(audio: Path) -> str:
    """Why this file cannot be a recording, in French, or "" if it can.

    Asked **before** anything heavy starts. A file that is not sound gave an
    `av.error.InvalidDataError` and a page of Python traceback -- after twenty
    seconds spent loading the models, since the chain only met the file once
    everything else was in memory. Reading a header costs milliseconds.
    """
    import soundfile

    if not audio.exists():
        return f"{audio.name} n'existe pas."
    try:
        if audio.stat().st_size == 0:
            return f"{audio.name} est vide."
    except OSError as trouble:
        return f"{audio.name} est illisible : {trouble.strerror or trouble}."
    try:
        renseignements = soundfile.info(str(audio))
    except (RuntimeError, OSError):
        return (
            f"{audio.name} n'est pas un enregistrement lisible : son en-tête ne "
            "dit pas de quel son il s'agit. Le fichier est peut-être incomplet, "
            "ou ce n'est pas un fichier audio."
        )
    if renseignements.frames <= 0:
        return f"{audio.name} ne contient aucun son."
    return ""
