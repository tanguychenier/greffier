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

from greffier.domaine.canaux import en_visio, tours_locaux
from greffier.domaine.modeles import Intervalle

#: Fenêtre de mesure des niveaux. 25 ms est la durée usuelle d'une trame de
#: parole : plus court mesure du bruit, plus long noie les débuts de mot.
TRAME_S = 0.025

#: En deçà de ce niveau efficace, un canal de la boucle est tenu pour muet :
#: aucun son n'y a été joué.
_PLANCHER_RMS = 1e-5

#: Plancher du logarithme, pour qu'un silence numérique ne donne pas -inf.
_PLANCHER_LOG = 1e-12


@dataclass(frozen=True)
class Canaux:
    """Les deux provenances, séparées, et ce qu'elles impliquent."""

    micro: np.ndarray | None
    systeme: np.ndarray
    #: Réunion tenue à distance. Faux pour un portable posé sur une table : la
    #: boucle système ne porte alors rien, tout le monde parle dans le micro, et
    #: la provenance n'identifie plus personne.
    distante: bool


def niveaux_par_trame(signal: np.ndarray, frequence: int) -> list[float]:
    """Niveau de chaque trame, en décibels. Le domaine ne veut que ça."""
    pas = int(frequence * TRAME_S) or 1
    utiles = len(signal) // pas
    if utiles == 0:
        return []
    trames = signal[: utiles * pas].reshape(utiles, pas)
    rms = np.sqrt(np.mean(trames.astype(np.float64) ** 2, axis=1))
    return [float(x) for x in 20 * np.log10(np.maximum(rms, _PLANCHER_LOG))]


def separer_canaux(
    donnees: np.ndarray, frequence: int = 16000, distante: bool | None = None
) -> Canaux:
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
    if donnees.ndim < 2 or donnees.shape[1] < 2:
        # Un fichier mono, un enregistrement importé : rien à séparer.
        mono = donnees if donnees.ndim == 1 else donnees[:, 0]
        return Canaux(micro=None, systeme=mono, distante=False)
    boucle = donnees[:, 1:]
    actifs = [
        i for i in range(boucle.shape[1])
        if float(np.sqrt(np.mean(boucle[:, i] ** 2))) > _PLANCHER_RMS
    ]
    micro = donnees[:, 0]
    if not actifs:
        # Boucle muette. En visio établie, cela veut dire que personne d'autre
        # n'a parlé pendant ce passage : tout ce qui est sur le micro est local.
        if distante:
            return Canaux(micro=micro, systeme=boucle.mean(axis=1), distante=True)
        return Canaux(micro=micro, systeme=micro, distante=False)
    # Un canal muet ne doit pas diviser l'amplitude des autres.
    systeme = boucle[:, actifs].mean(axis=1)
    if distante:
        return Canaux(micro=micro, systeme=systeme, distante=True)
    # Une boucle non nulle ne suffit pas à conclure « visio » : sur une réunion
    # de table, elle relevait -53 dB, du son y ayant fui. Ce qui tranche, c'est
    # de savoir si les autres dominent le micro une part notable du temps, ce
    # qui n'arrive jamais autour d'une table.
    if not en_visio(
        niveaux_par_trame(micro, frequence), niveaux_par_trame(systeme, frequence)
    ):
        return Canaux(micro=micro, systeme=micro, distante=False)
    return Canaux(micro=micro, systeme=systeme, distante=True)


class LecteurCanauxFichier:
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

    def passages_locaux(self, audio: Path) -> list[Intervalle]:
        """Les moments où la personne qui enregistre parle, dans ce fichier.

        Vide en présentiel, et c'est correct : autour d'une table, le canal ne
        désigne personne. Le direct affichera alors des voix à nommer plutôt
        qu'un « Toi » qui serait faux pour la moitié des passages.
        """
        try:
            donnees, frequence = sf.read(audio, dtype="float32", always_2d=True)
        except (OSError, RuntimeError):
            # Une tranche découpée pendant l'écriture peut être illisible : la
            # réunion continue, la tranche suivante repassera dessus.
            return []
        canaux = separer_canaux(donnees, frequence, distante=self.distante or None)
        self.distante = self.distante or canaux.distante
        if not canaux.distante or canaux.micro is None:
            return []
        return tours_locaux(
            niveaux_par_trame(canaux.micro, frequence),
            niveaux_par_trame(canaux.systeme, frequence),
            TRAME_S,
        )
