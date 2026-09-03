"""Transcription par faster-whisper, partout où whisper.cpp n'est pas empaqueté.

Même modèle, même qualité ; l'implémentation diffère. Sur macOS, whisper.cpp
reste préféré : l'accélération Metal le rend nettement plus rapide.
"""

from __future__ import annotations

from pathlib import Path

from greffier.domaine.modeles import Intervalle, Replique


class TranscripteurFasterWhisper:
    def __init__(self, taille: str = "large-v3", peripherique: str = "auto") -> None:
        self.taille = taille
        self.peripherique = peripherique
        self._modele = None

    def _charger(self) -> object:
        # Chargement tardif : le modèle pèse plus d'un gigaoctet en mémoire, il
        # n'a pas à être là quand on se contente de lister des réunions.
        if self._modele is None:
            from faster_whisper import WhisperModel

            self._modele = WhisperModel(
                self.taille, device=self.peripherique, compute_type="int8"
            )
        return self._modele

    def transcrire(self, audio: Path, langue: str, amorce: str) -> list[Replique]:
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
        return [
            Replique(intervalle=Intervalle(s.start, s.end), texte=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
