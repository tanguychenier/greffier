"""Transcription par whisper.cpp, accéléré Metal sur macOS.

Environ huit fois plus rapide que le temps réel sur un Mac Apple Silicon : une
réunion d'une heure est transcrite en quelques minutes.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from greffier.domaine.modeles import Intervalle, Replique

_HORAIRE = re.compile(
    r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d\d\d)"
)


def _secondes(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def lire_srt(chemin: Path) -> list[Replique]:
    """Extrait les répliques d'un fichier de sous-titres."""
    repliques: list[Replique] = []
    contenu = chemin.read_text(encoding="utf-8").strip()
    if not contenu:
        return repliques
    for bloc in re.split(r"\n\s*\n", contenu):
        lignes = [ligne for ligne in bloc.splitlines() if ligne.strip()]
        horaire = next(
            (_HORAIRE.search(ligne) for ligne in lignes if _HORAIRE.search(ligne)), None
        )
        if not horaire:
            continue
        texte = " ".join(
            ligne.strip() for ligne in lignes
            if not _HORAIRE.search(ligne) and not ligne.strip().isdigit()
        )
        # whisper --diarize préfixe « (speaker N) » : la diarisation sérieuse se
        # fait ailleurs, on retire l'étiquette.
        texte = re.sub(r"^\(speaker \d+\)\s*", "", texte).strip()
        if texte:
            repliques.append(Replique(
                intervalle=Intervalle(_secondes(*horaire.groups()[:4]),
                                      _secondes(*horaire.groups()[4:])),
                texte=texte,
            ))
    return repliques


class TranscripteurWhisperCpp:
    def __init__(self, modele: Path, vad: Path | None = None, fils: int = 8) -> None:
        if not modele.exists():
            raise FileNotFoundError(f"modèle de transcription introuvable : {modele}")
        self.modele = modele
        self.vad = vad if vad and vad.exists() else None
        self.fils = fils

    def transcrire(self, audio: Path, langue: str, amorce: str) -> list[Replique]:
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier) / audio.stem
            commande = [
                "whisper-cli", "-m", str(self.modele), "-f", str(audio),
                # Langue vide : « auto », et whisper la reconnaît lui-même. La
                # même convention que le micro vide, qui laisse choisir à
                # l'écoute plutôt qu'à la forme.
                "-l", langue or "auto", "-t", str(self.fils), "-osrt", "-of", str(base),
            ]
            if self.vad:
                commande += ["--vad", "--vad-model", str(self.vad)]
            if amorce:
                commande += ["--prompt", amorce]
            resultat = subprocess.run(commande, capture_output=True, text=True, check=False)
            srt = base.with_suffix(".srt")
            if resultat.returncode != 0 or not srt.exists():
                derniere = (resultat.stderr or resultat.stdout).strip().splitlines()
                raise RuntimeError(
                    "whisper-cli a échoué" + (f" : {derniere[-1]}" if derniere else "")
                )
            return lire_srt(srt)
