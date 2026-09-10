"""Ce que les canaux d'un enregistrement disent de la provenance du son.

Le premier canal porte le micro, les suivants la boucle système. De là se
déduisent deux choses qu'aucun modèle n'a besoin d'établir : si la réunion s'est
tenue à distance, et quels passages viennent de la personne qui enregistre.

Ce savoir vivait dans la diarisation, où lui seul l'utilisait. Le direct en a
besoin aussi, et **deux implémentations de « qui parle par quel canal » qui
divergent seraient pires qu'une duplication visible** : la fenêtre afficherait
un locuteur que le compte rendu contredirait. D'où ce module, importé par les
deux, et testable sans charger un modèle.
"""

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
    """Les deux provenances, séparées, et ce qu'elles impliquent."""

    mic: np.ndarray | None
    system: np.ndarray
    distante: bool

def levels_per_frame(signal: np.ndarray, frequency: int) -> list[float]:
    """Niveau de chaque trame, en décibels. Le domaine ne veut que ça."""
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
    """Sépare le micro de la boucle, et dit si la réunion était à distance.

    `distante` impose la réponse au lieu de la chercher. C'est ce dont le direct
    a besoin : le verdict se lit sur l'ensemble d'une réunion, pas sur dix
    secondes. Une tranche où seule la personne au micro parle ne montre aucune
    boucle dominante, donc se lirait « présentiel » — et sa voix, cessant d'être
    reconnue par le canal, deviendrait un participant distant de plus.

    Une boucle muette veut dire qu'aucun son n'a été joué par la machine : la
    réunion s'est tenue autour d'une table, et **tout le monde parle dans le
    même micro**.

    C'est une distinction qui décide de tout. En visio, la provenance identifie
    la personne qui enregistre avec certitude. En présentiel, elle n'identifie
    personne, et l'appliquer quand même ferait de tous les participants une
    seule voix. Mesuré : trois locuteurs autour d'une table ramenés à une seule
    étiquette « moi ».
    """
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
    """Lit un enregistrement et rend les passages venus du micro.

    Sert le port `LecteurDeCanaux` : le direct a besoin de savoir, pour chaque
    phrase transcrite, si elle vient de la personne qui enregistre — la seule
    attribution qui ne se trompe jamais.

    **Un objet, et non une fonction**, parce qu'il retient une chose : une
    réunion tenue à distance l'est jusqu'au bout. Le verdict se lit sur
    l'ensemble de l'audio, pas sur dix secondes ; sans cette mémoire, une tranche
    où personne d'autre ne parle se lit « présentiel », et la voix de la personne
    au micro devient un participant de plus. Mesuré à l'essai sur la première
    tranche d'une réunion, avant que quiconque d'autre ait pris la parole.
    """

    def __init__(self) -> None:
        self.distante = False

    def local_passages(self, audio: Path) -> list[Span]:
        """Les moments où la personne qui enregistre parle, dans ce fichier.

        Vide en présentiel, et c'est correct : autour d'une table, le canal ne
        désigne personne. Le direct affichera alors des voix à nommer plutôt
        qu'un « Toi » qui serait faux pour la moitié des passages.
        """
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
