"""Niveaux audio pendant l'enregistrement, lus dans le fichier en cours d'écriture.

L'interface doit montrer qui parle, maintenant. Ouvrir une seconde fois le
périphérique de capture, en parallèle de ffmpeg, demanderait une bibliothèque
audio de plus et risquerait le conflit d'accès. On lit donc la queue du fichier
que ffmpeg est en train d'écrire : c'est exactement ce qui sera transcrit, et
aucun périphérique n'est ouvert deux fois.

Le fichier n'est pas encore refermé, donc son en-tête annonce une taille fausse
ou nulle. On ne se fie qu'au format déclaré dans les premiers octets, et on lit
les derniers échantillons directement, sans passer par un lecteur qui exigerait
un fichier complet.
"""

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
    """Ce que l'en-tête du fichier dit du format."""

    channels: int
    frequency: int
    octets_par_echantillon: int
    debut_donnees: int

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.octets_par_echantillon

@dataclass(frozen=True)
class LevelReading:
    """Un instantané des niveaux, prêt pour l'affichage."""

    micro_db: float
    systeme_db: float
    qui: WhoSpeaks

    @property
    def micro_part(self) -> float:
        """Niveau du micro ramené entre 0 et 1, pour un vumètre."""
        return _part(self.micro_db)

    @property
    def systeme_part(self) -> float:
        return _part(self.systeme_db)

def _part(db: float) -> float:
    """Convertit des décibels en fraction affichable.

    L'échelle va de -60 dB (silence) à -10 dB (parole forte) : au-delà, un
    vumètre saturé n'apprend plus rien, et en dessous il ne montre que du bruit.
    """
    return max(0.0, min(1.0, (db + 60.0) / 50.0))

def lire_forme(audio: Path) -> Shape | None:
    """Lit le format et l'endroit où commencent les échantillons.

    Les chunks sont parcourus jusqu'à « data » plutôt que d'en supposer la
    longueur : l'en-tête d'un enregistrement réel fait 102 octets, pas 44, et
    lire à la mauvaise base entrelace les canaux de travers.
    """
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
                octets_par_echantillon=bits // 8, debut_donnees=corps,
            )
        position = corps + taille + (taille % 2)
    return None

def read_level(audio: Path, fenetre_s: float = FENETRE_S) -> LevelReading | None:
    """Les niveaux des dernières fractions de seconde écrites.

    Rend `None` quand il n'y a encore rien d'exploitable : l'appelant affiche
    alors un état d'attente plutôt qu'un zéro, qui se lirait comme du silence.
    """
    forme = lire_forme(audio)
    if forme is None or forme.octets_par_echantillon != 2:
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
    micro_db, systeme_db = _decibels(mic), _decibels(system)
    return LevelReading(
        micro_db=micro_db,
        systeme_db=systeme_db,
        qui=who_speaks(micro_db, systeme_db),
    )

def _decibels(signal: np.ndarray) -> float:
    if signal.size == 0:
        return -120.0
    return float(20 * np.log10(max(float(np.sqrt(np.mean(signal**2))), 1e-12)))

def written_duration(audio: Path) -> float | None:
    """Combien de son le fichier porte réellement, pendant qu'il s'écrit.

    Pas `soundfile`, pas l'en-tête : tant que ffmpeg n'a pas refermé le fichier,
    la taille qu'il annonce est fausse ou nulle. On compte les octets présents,
    ce qui donne la seule position juste dans l'enregistrement.

    C'est cette durée que suit la transcription en direct, et non l'horloge de la
    réunion : après une pause, les deux ont divergé de tout le temps d'arrêt, et
    transcrire à la position de l'horloge relisait un passage déjà vu — ou lisait
    au-delà de ce qui est écrit, donc rien.
    """
    forme = lire_forme(audio)
    if forme is None:
        return None
    try:
        taille = audio.stat().st_size
    except OSError:
        return None
    utiles = max(0, taille - forme.debut_donnees)
    return utiles / (forme.frequency * forme.bytes_per_frame)
