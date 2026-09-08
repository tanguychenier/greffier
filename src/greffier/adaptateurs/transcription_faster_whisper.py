"""Transcription par faster-whisper, partout où whisper.cpp n'est pas empaqueté.

Même modèle, même qualité ; l'implémentation diffère. Sur macOS, whisper.cpp
reste préféré : l'accélération Metal le rend nettement plus rapide.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib.util
from pathlib import Path

from greffier.domaine.modeles import Intervalle, Replique

#: Les bibliothèques CUDA à charger, dans cet ordre : cuBLASLt avant cuBLAS,
#: qui en dépend, et cuDNN avant que CTranslate2 ne le réclame.
_BIBLIOTHEQUES_CUDA = (
    "cublas/lib/libcublasLt.so*",
    "cublas/lib/libcublas.so*",
    "cudnn/lib/libcudnn*.so*",
    "cuda_nvrtc/lib/libnvrtc.so*",
)


def bibliotheques_cuda() -> list[Path]:
    """Les bibliothèques que posent les roues « nvidia-* », prêtes à charger.

    Ces roues les déposent dans le dossier des paquets, hors du chemin où le
    chargeur du système va les chercher : CTranslate2 ne les trouvait pas et se
    rabattait sur le processeur, treize fois plus lent. La seule autre façon de
    les lui montrer est de régler `LD_LIBRARY_PATH` avant de lancer Greffier,
    ce qu'aucun raccourci de bureau ne fait.

    Rend une liste vide quand les roues ne sont pas installées, ce qui est le
    cas ordinaire : elles ne servent qu'à une carte NVIDIA.
    """
    paquet = importlib.util.find_spec("nvidia")
    if paquet is None or not paquet.submodule_search_locations:
        return []
    racine = Path(next(iter(paquet.submodule_search_locations)))
    return [
        chemin
        for motif in _BIBLIOTHEQUES_CUDA
        for chemin in sorted(racine.glob(motif))
    ]


def _montrer_cuda_au_chargeur() -> None:
    """Charge ce que `bibliotheques_cuda` a trouvé, sans jamais faire échouer.

    Une bibliothèque illisible n'est pas une raison de renoncer à transcrire :
    la carte sera simplement inutilisable, et le repli sur le processeur s'en
    chargera.
    """
    for chemin in bibliotheques_cuda():
        with contextlib.suppress(OSError):
            ctypes.CDLL(str(chemin), mode=ctypes.RTLD_GLOBAL)


class TranscripteurFasterWhisper:
    def __init__(self, taille: str = "large-v3", peripherique: str = "auto") -> None:
        self.taille = taille
        self.peripherique = peripherique
        self._modele = None

    def _charger(self) -> object:
        # Chargement tardif : le modèle pèse plus d'un gigaoctet en mémoire, il
        # n'a pas à être là quand on se contente de lister des réunions.
        if self._modele is None:
            _montrer_cuda_au_chargeur()
            from faster_whisper import WhisperModel

            self._modele = WhisperModel(
                self.taille, device=self.peripherique, compute_type="int8"
            )
        return self._modele

    def transcrire(self, audio: Path, langue: str, amorce: str) -> list[Replique]:
        try:
            return self._repliques(audio, langue, amorce)
        except RuntimeError:
            if self.peripherique == "cpu":
                raise
            # « auto » retient la carte graphique dès qu'il en voit une, sans
            # vérifier que les bibliothèques CUDA l'accompagnent. Sur un poste
            # doté d'une carte mais sans cuBLAS — le cas ordinaire sous Linux,
            # où rien ne les installe — le modèle se chargeait sans broncher,
            # puis la transcription échouait au premier bloc audio. Le
            # processeur est plus lent, mais il transcrit.
            self.peripherique = "cpu"
            self._modele = None
            return self._repliques(audio, langue, amorce)

    def _repliques(self, audio: Path, langue: str, amorce: str) -> list[Replique]:
        segments, _ = self._charger().transcribe(  # type: ignore[attr-defined]
            str(audio),
            # None, pas la chaîne « auto » : faster-whisper refuse un code de
            # langue inconnu, là où l'absence de code déclenche la détection.
            language=langue or None,
            initial_prompt=amorce or None,
            # Le découpage par détection de parole évite que le modèle brode sur
            # les silences — travers classique de whisper sur les longs blancs.
            vad_filter=True,
        )
        # La liste est construite ici, et non rendue paresseusement : les
        # segments sont un générateur, et c'est en le parcourant que le calcul a
        # lieu — donc aussi qu'échoue une carte graphique inutilisable.
        return [
            Replique(intervalle=Intervalle(s.start, s.end), texte=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
