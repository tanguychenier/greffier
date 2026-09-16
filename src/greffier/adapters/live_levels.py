"""Audio levels during the recording, read from the file being written."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from greffier.domain.channels import WhoSpeaks, who_speaks

_MINIMAL_HEADER = 44

WINDOW_S = 0.25

@dataclass(frozen=True)
class Shape:
    """What the file header says about the format."""

    channels: int
    frequency: int
    bytes_per_sample: int
    data_start: int

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.bytes_per_sample

@dataclass(frozen=True)
class LevelReading:
    """A snapshot of the levels, ready to display."""

    mic_db: float
    system_db: float
    who: WhoSpeaks

    @property
    def mic_share(self) -> float:
        """The mic level brought between 0 and 1, for a meter."""
        return _part(self.mic_db)

    @property
    def system_share(self) -> float:
        return _part(self.system_db)

def _part(db: float) -> float:
    """Converts decibels into a displayable fraction."""
    return max(0.0, min(1.0, (db + 60.0) / 50.0))

def read_shape(audio: Path) -> Shape | None:
    """Reads the format and where the samples start."""
    try:
        with audio.open("rb") as file:
            header = file.read(1024)
    except OSError:
        return None
    if len(header) < _MINIMAL_HEADER or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        return None

    channels = frequency = bits = 0
    position = 12
    while position + 8 <= len(header):
        name = header[position:position + 4]
        size = struct.unpack_from("<I", header, position + 4)[0]
        corps = position + 8
        if name == b"fmt " and corps + 16 <= len(header):
            channels, frequency = struct.unpack_from("<HI", header, corps + 2)
            bits = struct.unpack_from("<H", header, corps + 14)[0]
        elif name == b"data":
            if channels < 1 or frequency < 1 or bits not in (8, 16, 24, 32):
                return None
            return Shape(
                channels=channels, frequency=frequency,
                bytes_per_sample=bits // 8, data_start=corps,
            )
        position = corps + size + (size % 2)
    return None

def read_level(
    audio: Path, window_s: float = WINDOW_S, up_to: float | None = None
) -> LevelReading | None:
    """The levels of the last fractions of a second written.

    `up_to`, in seconds, reads the window that ends there instead of at the
    end of the file: a recording replayed from a finished file has its "now"
    somewhere in the middle.
    """
    shape = read_shape(audio)
    if shape is None or shape.bytes_per_sample != 2:
        return None
    wanted_one = int(shape.frequency * window_s) * shape.bytes_per_frame
    try:
        size = audio.stat().st_size
        if up_to is not None:
            frames = int(up_to * shape.frequency)
            size = min(size, shape.data_start + frames * shape.bytes_per_frame)
        if size <= shape.data_start:
            return None
        with audio.open("rb") as file:
            depart = max(shape.data_start, size - wanted_one)
            depart -= (depart - shape.data_start) % shape.bytes_per_frame
            file.seek(depart)
            brut = file.read(wanted_one)
    except OSError:
        return None

    frame_count = len(brut) // shape.bytes_per_frame
    if frame_count == 0:
        return None
    samples = np.frombuffer(brut[: frame_count * shape.bytes_per_frame], dtype="<i2")
    channels = samples.reshape(frame_count, shape.channels).astype(np.float64) / 32768.0

    mic = channels[:, 0]
    system = channels[:, 1:].mean(axis=1) if shape.channels > 1 else np.zeros(frame_count)
    mic_db, system_db = _decibels(mic), _decibels(system)
    return LevelReading(
        mic_db=mic_db,
        system_db=system_db,
        who=who_speaks(mic_db, system_db),
    )

def _decibels(signal: np.ndarray) -> float:
    if signal.size == 0:
        return -120.0
    return float(20 * np.log10(max(float(np.sqrt(np.mean(signal**2))), 1e-12)))

def written_duration(audio: Path) -> float | None:
    """How much sound the file actually holds."""
    shape = read_shape(audio)
    if shape is None:
        return None
    try:
        size = audio.stat().st_size
    except OSError:
        return None
    useful_ones = max(0, size - shape.data_start)
    return useful_ones / (shape.frequency * shape.bytes_per_frame)
