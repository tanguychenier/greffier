"""Giving the assistant a voice that can be listened to without wincing.

sherpa-onnx is already loaded for segmentation, so no new dependency and no
network call. Measured: 4.9 times real time.
"""

from __future__ import annotations

import contextlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from greffier.adapters import cuda
from greffier.domain.arithmetic import AUTO, CARD, chosen_device

SYSTEM = platform.system()

FRENCH_VOICE = 0

ESPEAK_LANGUAGE = {"fr": "fr", "en": "en-us", "es": "es", "it": "it", "pt": "pt"}

RATE = 0.95

SENTENCE_ENDS = re.compile(r"(?<=[.!?…])\s+")

DASHES = re.compile(r"\s*[—–-]\s*")

def clean(text: str) -> str:
    """What is pronounced, stripped of what is not."""
    without_dashes = DASHES.sub(", ", text)
    return re.sub(r"\s+", " ", without_dashes).strip()

def sentences(text: str, maximum: int = 240) -> list[str]:
    """Cuts into pronounceable pieces, earliest first."""
    chunks: list[str] = []
    for sentence in SENTENCE_ENDS.split(clean(text)):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= maximum:
            chunks.append(sentence)
            continue
        current = ""
        for bout in sentence.split(", "):
            if current and len(current) + len(bout) + 2 > maximum:
                chunks.append(current)
                current = bout
            else:
                current = f"{current}, {bout}" if current else bout
        if current:
            chunks.append(current)
    return chunks

def player() -> list[str] | None:
    """The command that plays a wav file, according to the system."""
    if SYSTEM == "Darwin" and shutil.which("afplay"):
        return ["afplay"]
    for name in ("paplay", "aplay", "ffplay"):
        path = shutil.which(name)
        if path:
            return [path, "-nodisp", "-autoexit", "-loglevel", "error"] \
                if name == "ffplay" else [path]
    if SYSTEM == "Windows" and shutil.which("powershell"):
        return ["powershell", "-NoProfile", "-Command"]
    return None

@contextlib.contextmanager
def _without_chatter() -> Iterator[None]:
    """Muffles what the native library writes to standard error."""
    try:
        copy_ = os.dup(2)
    except OSError:
        yield
        return
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 2)
        yield
    finally:
        os.dup2(copy_, 2)
        os.close(copy_)

_OPENED: dict[tuple[str, str, str, int], Any] = {}

_TURN = threading.Lock()

class NeuralVoice:
    """Pronounces a text with a neural voice, locally."""

    def __init__(self, folder: Path, language: str = "fr", voice: int = FRENCH_VOICE,
                 rate: float = RATE, threads: int = 4,
                 gag: Path | None = None, device: str = AUTO) -> None:
        self.gag = Path(gag) if gag else None
        self.folder = Path(folder)
        self.language = language
        self.voice = voice
        self.rate = rate
        self.threads = threads
        self.device = device
        self._engine = None
        self._lock = threading.Lock()
        self._reading: subprocess.Popen[bytes] | None = None
        self._interrupted = threading.Event()

    @property
    def installed(self) -> bool:
        """A network and its vocabulary are enough, whatever the family."""
        return self._network.exists() and (self.folder / "tokens.txt").exists()

    @property
    def available(self) -> bool:
        return self.installed and player() is not None

    def _load(self) -> Any:
        """Loads whichever model is present, Kokoro or VITS.

        Opened once per folder, language and device for the whole process.
        Somebody preparing a meeting out loud gets a new voice built on every
        question, and the model takes five to six seconds to open -- longer than
        the answer it was waiting for. Saying the remark itself takes 2.43 s on
        the processor and 0.28 s on the card: the opening was the whole wait.
        """
        if self._engine is not None:
            return self._engine
        where = chosen_device(self.device, cuda.a_card_is_usable())
        clef = (str(self.folder), self.language, where, self.threads)
        with _TURN:
            ready = _OPENED.get(clef)
            if ready is None:
                ready = self._open(where)
                _OPENED[clef] = ready
        self._engine = ready
        return ready

    def warm(self) -> None:
        """Opens the model now, saying nothing.

        Called from a thread while somebody is still typing: a failure here
        costs nothing, since the answer will open it again and say so properly.
        """
        with contextlib.suppress(Exception):
            self._load()

    def _open(self, where: str) -> Any:
        if where == CARD:
            cuda.show_to_the_loader()
        import sherpa_onnx

        shared_one = {
            "tokens": str(self.folder / "tokens.txt"),
            "data_dir": str(self.folder / "espeak-ng-data"),
        }
        if self._voice_table.exists():
            model = sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(self._network), voices=str(self._voice_table),
                    lang=ESPEAK_LANGUAGE.get(self.language, self.language), **shared_one,
                ),
                num_threads=self.threads,
                provider=where,
            )
        else:
            model = sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(self._network), **shared_one),
                num_threads=self.threads,
                provider=where,
            )
        configuration = sherpa_onnx.OfflineTtsConfig(model=model)
        if not configuration.validate():
            raise RuntimeError("configuration de synthèse vocale invalide")
        return sherpa_onnx.OfflineTts(configuration)

    @property
    def _voice_table(self) -> Path:
        return self.folder / "voices.bin"

    @property
    def _network(self) -> Path:
        """The weights file. Named model.onnx by Kokoro, otherwise the first .onnx."""
        expected = self.folder / "model.onnx"
        if expected.exists():
            return expected
        return next(iter(sorted(self.folder.glob("*.onnx"))), expected)

    def build_one(self, text: str, destination: Path) -> Path | None:
        """Writes the spoken text into a file, without playing it."""
        import soundfile

        remark = clean(text)
        if not remark:
            return None
        with _without_chatter():
            rendered = self._load().generate(remark, sid=self.voice, speed=self.rate)
        if len(rendered.samples) == 0:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(destination), rendered.samples, rendered.sample_rate)
        return destination

    def say(self, text: str) -> bool:
        """Pronounces the text, sentence by sentence, handing back in between.

        Refuses while it is already speaking, and that is the fix: it used to
        cut itself here. A second remark arriving mid-sentence killed the first
        one, "sometimes she starts talking and it cuts". Interrupting oneself
        is never what was wanted; the room already got an answer.
        """
        chunks = sentences(text)
        if not chunks or not self.available:
            return False
        if self.is_speaking():
            return False
        self._interrupted.clear()
        threading.Thread(target=self._pronounce, args=(chunks,), daemon=True).start()
        return True

    def _pronounce(self, chunks: list[str]) -> None:
        import soundfile

        with tempfile.TemporaryDirectory() as folder:
            for rank, chunk in enumerate(chunks):
                if self._interrupted.is_set():
                    return
                try:
                    with _without_chatter():
                        rendered = self._load().generate(
                            chunk, sid=self.voice, speed=self.rate)
                except (RuntimeError, OSError):
                    return
                if len(rendered.samples) == 0:
                    continue
                file = Path(folder) / f"{rank}.wav"
                soundfile.write(str(file), rendered.samples, rendered.sample_rate)
                if not self._play(file):
                    return

    def _play(self, file: Path) -> bool:
        """Plays a file and waits for it. False when it was cut."""
        command = player()
        if command is None:
            return False
        command = (
            [*command, f"(New-Object Media.SoundPlayer '{file}').PlaySync()"]
            if command[0] == "powershell" else [*command, str(file)]
        )
        try:
            with self._lock:
                if self._interrupted.is_set():
                    return False
                self._reading = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._publish_the_gag(self._reading.pid)
            code = self._reading.wait()
        except OSError:
            return False
        finally:
            self._publish_the_gag(None)
        if code is not None and code < 0:
            self._interrupted.set()
            return False
        return not self._interrupted.is_set()

    def _publish_the_gag(self, pid: int | None) -> None:
        """Tells whoever wants to cut which process is playing the sound."""
        if self.gag is None:
            return
        with contextlib.suppress(OSError):
            if pid is None:
                self.gag.unlink(missing_ok=True)
            else:
                self.gag.parent.mkdir(parents=True, exist_ok=True)
                self.gag.write_text(str(pid), encoding="utf-8")

    def is_speaking(self) -> bool:
        with self._lock:
            return self._reading is not None and self._reading.poll() is None

    def go_quiet(self) -> None:
        """Cuts the current remark, sentences still to come included.

        Measured at 26 ms. Cutting only the current sentence let the next one resume,
        which reads as a button that does not work.
        """
        self._interrupted.set()
        with self._lock:
            reading, self._reading = self._reading, None
        if reading is not None and reading.poll() is None:
            reading.terminate()
            try:
                reading.wait(timeout=2)
            except subprocess.TimeoutExpired:
                reading.kill()

def silence(gag: Path) -> bool:
    """Cuts the sound under way, from any process."""
    import signal

    try:
        pid = int(gag.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return False
    with contextlib.suppress(OSError):
        gag.unlink(missing_ok=True)
    return True
