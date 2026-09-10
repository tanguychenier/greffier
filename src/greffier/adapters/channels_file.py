"""What a recording's channels say about who is speaking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from greffier.domain.channels import local_turns, over_video
from greffier.domain.models import Span

TRAME_S = 0.025

_PLANCHER_RMS = 1e-5

_PLANCHER_LOG = 1e-12

@dataclass(frozen=True)
class Channels:
    """The two origins, separated, and what they carry."""

    mic: np.ndarray | None
    system: np.ndarray
    distante: bool

def levels_per_frame(signal: np.ndarray, frequency: int) -> list[float]:
    """The level of each frame, in decibels."""
    pas = int(frequency * TRAME_S) or 1
    utiles = len(signal) // pas
    if utiles == 0:
        return []
    trames = signal[: utiles * pas].reshape(utiles, pas)
    rms = np.sqrt(np.mean(trames.astype(np.float64) ** 2, axis=1))
    return [float(x) for x in 20 * np.log10(np.maximum(rms, _PLANCHER_LOG))]

def separer_canaux(
    data: np.ndarray, frequency: int = 16000, distante: bool | None = None
) -> Channels:
    """Separates the mic from the loopback, and says whether it was remote."""
    if data.ndim < 2 or data.shape[1] < 2:
        mono = data if data.ndim == 1 else data[:, 0]
        return Channels(mic=None, system=mono, distante=False)
    boucle = data[:, 1:]
    actifs = [
        i for i in range(boucle.shape[1])
        if float(np.sqrt(np.mean(boucle[:, i] ** 2))) > _PLANCHER_RMS
    ]
    mic = data[:, 0]
    if not actifs:
        if distante:
            return Channels(mic=mic, system=boucle.mean(axis=1), distante=True)
        return Channels(mic=mic, system=mic, distante=False)
    system = boucle[:, actifs].mean(axis=1)
    if distante:
        return Channels(mic=mic, system=system, distante=True)
    if not over_video(
        levels_per_frame(mic, frequency), levels_per_frame(system, frequency)
    ):
        return Channels(mic=mic, system=mic, distante=False)
    return Channels(mic=mic, system=system, distante=True)

class FileChannelReader:
    """Reads a recording and returns the passages from the mic."""

    def __init__(self) -> None:
        self.distante = False

    def local_passages(self, audio: Path) -> list[Span]:
        """The moments when the person recording speaks themselves."""
        try:
            data, frequency = sf.read(audio, dtype="float32", always_2d=True)
        except (OSError, RuntimeError):
            return []
        channels = separer_canaux(data, frequency, distante=self.distante or None)
        self.distante = self.distante or channels.distante
        if not channels.distante or channels.mic is None:
            return []
        return local_turns(
            levels_per_frame(channels.mic, frequency),
            levels_per_frame(channels.system, frequency),
            TRAME_S,
        )
