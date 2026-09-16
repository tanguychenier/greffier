"""What a recording's channels say about who is speaking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from greffier.domain.channels import local_turns, over_video
from greffier.domain.models import Span

FRAME_S = 0.025

_RMS_FLOOR = 1e-5

_LOG_FLOOR = 1e-12

@dataclass(frozen=True)
class Channels:
    """The two origins, separated, and what they carry."""

    mic: np.ndarray | None
    system: np.ndarray
    remote: bool

def levels_per_frame(signal: np.ndarray, frequency: int) -> list[float]:
    """The level of each frame, in decibels."""
    step = int(frequency * FRAME_S) or 1
    useful_ones = len(signal) // step
    if useful_ones == 0:
        return []
    frame_count = signal[: useful_ones * step].reshape(useful_ones, step)
    rms = np.sqrt(np.mean(frame_count.astype(np.float64) ** 2, axis=1))
    return [float(x) for x in 20 * np.log10(np.maximum(rms, _LOG_FLOOR))]

def split_channels(
    data: np.ndarray, frequency: int = 16000, remote: bool | None = None
) -> Channels:
    """Separates the mic from the loopback, and says whether it was remote."""
    if data.ndim < 2 or data.shape[1] < 2:
        mono = data if data.ndim == 1 else data[:, 0]
        return Channels(mic=None, system=mono, remote=False)
    loop = data[:, 1:]
    active_ones = [
        i for i in range(loop.shape[1])
        if float(np.sqrt(np.mean(loop[:, i] ** 2))) > _RMS_FLOOR
    ]
    mic = data[:, 0]
    if not active_ones:
        if remote:
            return Channels(mic=mic, system=loop.mean(axis=1), remote=True)
        return Channels(mic=mic, system=mic, remote=False)
    system = loop[:, active_ones].mean(axis=1)
    if remote:
        return Channels(mic=mic, system=system, remote=True)
    if not over_video(
        levels_per_frame(mic, frequency), levels_per_frame(system, frequency)
    ):
        return Channels(mic=mic, system=mic, remote=False)
    return Channels(mic=mic, system=system, remote=True)

class FileChannelReader:
    """Reads a recording and returns the passages from the mic."""

    def __init__(self) -> None:
        self.remote = False

    def local_passages(self, audio: Path) -> list[Span]:
        """The moments when the person recording speaks themselves."""
        try:
            data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        except (OSError, RuntimeError):
            return []
        channels = split_channels(data, frequency, remote=self.remote or None)
        self.remote = self.remote or channels.remote
        if not channels.remote or channels.mic is None:
            return []
        return local_turns(
            levels_per_frame(channels.mic, frequency),
            levels_per_frame(channels.system, frequency),
            FRAME_S,
        )
