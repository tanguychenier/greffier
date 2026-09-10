"""Audio levels during the recording, read from the file being written."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from greffier.domain.channels import WhoSpeaks, who_speaks

_ENTETE_MINIMAL = 44

FENETRE_S = 0.25

@dataclass(frozen=True)
class Shape:
    """What the file header says about the format."""

    channels: int
    frequency: int
    bytes_per_sample: int
    debut_donnees: int

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
    def systeme_part(self) -> float:
        return _part(self.system_db)

def _part(db: float) -> float:
    """Converts decibels into a displayable fraction."""
    return max(0.0, min(1.0, (db + 60.0) / 50.0))

def lire_forme(audio: Path) -> Shape | None:
    """Reads the format and where the samples start."""
    try:
        with audio.open("rb") as file:
            header = file.read(1024)
    except OSError:
        return None
    if len(header) < _ENTETE_MINIMAL or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        return None

    channels = frequency = bits = 0
    position = 12
    while position + 8 <= len(header):
        name = header[position:position + 4]
        taille = struct.unpack_from("<I", header, position + 4)[0]
        corps = position + 8
        if name == b"fmt " and corps + 16 <= len(header):
            channels, frequency = struct.unpack_from("<HI", header, corps + 2)
            bits = struct.unpack_from("<H", header, corps + 14)[0]
        elif name == b"data":
            if channels < 1 or frequency < 1 or bits not in (8, 16, 24, 32):
                return None
            return Shape(
                channels=channels, frequency=frequency,
                bytes_per_sample=bits // 8, debut_donnees=corps,
            )
        position = corps + taille + (taille % 2)
    return None

def read_level(audio: Path, fenetre_s: float = FENETRE_S) -> LevelReading | None:
    """The levels of the last fractions of a second written."""
    forme = lire_forme(audio)
    if forme is None or forme.bytes_per_sample != 2:
        return None
    voulu = int(forme.frequency * fenetre_s) * forme.bytes_per_frame
    try:
        taille = audio.stat().st_size
        if taille <= forme.debut_donnees:
            return None
        with audio.open("rb") as file:
            depart = max(forme.debut_donnees, taille - voulu)
            depart -= (depart - forme.debut_donnees) % forme.bytes_per_frame
            file.seek(depart)
            brut = file.read(voulu)
    except OSError:
        return None

    trames = len(brut) // forme.bytes_per_frame
    if trames == 0:
        return None
    echantillons = np.frombuffer(brut[: trames * forme.bytes_per_frame], dtype="<i2")
    channels = echantillons.reshape(trames, forme.channels).astype(np.float64) / 32768.0

    mic = channels[:, 0]
    system = channels[:, 1:].mean(axis=1) if forme.channels > 1 else np.zeros(trames)
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
    forme = lire_forme(audio)
    if forme is None:
        return None
    try:
        taille = audio.stat().st_size
    except OSError:
        return None
    utiles = max(0, taille - forme.debut_donnees)
    return utiles / (forme.frequency * forme.bytes_per_frame)
