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

from greffier.domaine.canaux import QuiParle, qui_parle

#: Taille minimale d'un en-tête WAV : « RIFF », « WAVE », un « fmt » de 16
#: octets. La vraie taille se lit, elle ne se suppose pas — voir `lire_forme`.
_ENTETE_MINIMAL = 44

#: Durée observée à chaque relevé. Assez pour un niveau stable, assez court pour
#: qu'un vumètre suive la parole.
FENETRE_S = 0.25


@dataclass(frozen=True)
class Forme:
    """Ce que l'en-tête du fichier dit du format."""

    canaux: int
    frequence: int
    octets_par_echantillon: int
    #: Où commencent réellement les échantillons. **Pas 44.** ffmpeg écrit un
    #: « fmt » étendu de 40 octets et un chunk « LIST », ce qui porte l'en-tête
    #: à 102 octets sur un enregistrement réel. Supposer 44 décalait la lecture
    #: de 29 échantillons, donc de deux canaux sur trois : l'interface montrait
    #: « les autres parlent » quand c'était la personne qui enregistrait.
    debut_donnees: int

    @property
    def octets_par_trame(self) -> int:
        return self.canaux * self.octets_par_echantillon


@dataclass(frozen=True)
class Releve:
    """Un instantané des niveaux, prêt pour l'affichage."""

    micro_db: float
    systeme_db: float
    qui: QuiParle

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


def lire_forme(audio: Path) -> Forme | None:
    """Lit le format et l'endroit où commencent les échantillons.

    Les chunks sont parcourus jusqu'à « data » plutôt que d'en supposer la
    longueur : l'en-tête d'un enregistrement réel fait 102 octets, pas 44, et
    lire à la mauvaise base entrelace les canaux de travers.
    """
    try:
        with audio.open("rb") as fichier:
            entete = fichier.read(1024)
    except OSError:
        return None
    if len(entete) < _ENTETE_MINIMAL or entete[:4] != b"RIFF" or entete[8:12] != b"WAVE":
        return None

    canaux = frequence = bits = 0
    position = 12
    while position + 8 <= len(entete):
        nom = entete[position:position + 4]
        taille = struct.unpack_from("<I", entete, position + 4)[0]
        corps = position + 8
        if nom == b"fmt " and corps + 16 <= len(entete):
            canaux, frequence = struct.unpack_from("<HI", entete, corps + 2)
            bits = struct.unpack_from("<H", entete, corps + 14)[0]
        elif nom == b"data":
            if canaux < 1 or frequence < 1 or bits not in (8, 16, 24, 32):
                return None
            return Forme(
                canaux=canaux, frequence=frequence,
                octets_par_echantillon=bits // 8, debut_donnees=corps,
            )
        # Un chunk de taille impaire est suivi d'un octet de bourrage.
        position = corps + taille + (taille % 2)
    return None


def relever(audio: Path, fenetre_s: float = FENETRE_S) -> Releve | None:
    """Les niveaux des dernières fractions de seconde écrites.

    Rend `None` quand il n'y a encore rien d'exploitable : l'appelant affiche
    alors un état d'attente plutôt qu'un zéro, qui se lirait comme du silence.
    """
    forme = lire_forme(audio)
    if forme is None or forme.octets_par_echantillon != 2:
        # Seul le PCM 16 bits est produit par la chaîne ; le reste n'est pas
        # deviné, il est ignoré.
        return None
    voulu = int(forme.frequence * fenetre_s) * forme.octets_par_trame
    try:
        taille = audio.stat().st_size
        if taille <= forme.debut_donnees:
            return None
        with audio.open("rb") as fichier:
            depart = max(forme.debut_donnees, taille - voulu)
            # Se recaler sur une frontière de trame, comptée depuis le début
            # réel des données : lire à l'octet près entrelace les canaux et
            # inverse micro et système.
            depart -= (depart - forme.debut_donnees) % forme.octets_par_trame
            fichier.seek(depart)
            brut = fichier.read(voulu)
    except OSError:
        return None

    trames = len(brut) // forme.octets_par_trame
    if trames == 0:
        return None
    echantillons = np.frombuffer(brut[: trames * forme.octets_par_trame], dtype="<i2")
    canaux = echantillons.reshape(trames, forme.canaux).astype(np.float64) / 32768.0

    micro = canaux[:, 0]
    systeme = canaux[:, 1:].mean(axis=1) if forme.canaux > 1 else np.zeros(trames)
    micro_db, systeme_db = _decibels(micro), _decibels(systeme)
    return Releve(
        micro_db=micro_db,
        systeme_db=systeme_db,
        qui=qui_parle(micro_db, systeme_db),
    )


def _decibels(signal: np.ndarray) -> float:
    if signal.size == 0:
        return -120.0
    return float(20 * np.log10(max(float(np.sqrt(np.mean(signal**2))), 1e-12)))


def duree_ecrite(audio: Path) -> float | None:
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
    return utiles / (forme.frequence * forme.octets_par_trame)
