"""Ce que les deux moteurs reçoivent comme langue.

Le réglage vide veut dire « reconnais-la toi-même ». Les deux moteurs
l'expriment différemment, et se tromper est silencieux : whisper.cpp
transcrirait dans une langue arbitraire, faster-whisper refuserait un code
inconnu — dans les deux cas, une heure après le début de la réunion.
"""

import subprocess
from pathlib import Path

import pytest

from greffier.adaptateurs.transcription_whisper_cpp import TranscripteurWhisperCpp


@pytest.fixture
def modele(tmp_path):
    fichier = tmp_path / "ggml-small.bin"
    fichier.write_bytes(b"\0" * 16)
    return fichier


class TestWhisperCpp:
    def _commande(self, monkeypatch, modele, langue):
        vue: dict[str, list[str]] = {}

        def faux_run(commande, **_options):
            vue["commande"] = list(commande)
            # Un .srt vide suffit : c'est la commande qui est éprouvée.
            Path(commande[commande.index("-of") + 1] + ".srt").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(commande, 0, stdout="", stderr="")

        monkeypatch.setattr(
            "greffier.adaptateurs.transcription_whisper_cpp.subprocess.run", faux_run)
        TranscripteurWhisperCpp(modele).transcrire(modele, langue, "")
        return vue["commande"]

    def test_une_langue_donnee_est_transmise(self, monkeypatch, modele):
        commande = self._commande(monkeypatch, modele, "en")
        assert commande[commande.index("-l") + 1] == "en"

    def test_une_langue_vide_devient_auto(self, monkeypatch, modele):
        """« -l » attend une valeur : sans elle, l'option suivante serait avalée."""
        commande = self._commande(monkeypatch, modele, "")
        assert commande[commande.index("-l") + 1] == "auto"


class TestFasterWhisper:
    def _langue_recue(self, monkeypatch, langue):
        from greffier.adaptateurs import transcription_faster_whisper as adaptateur

        vue: dict[str, object] = {}

        class FauxModele:
            def transcribe(self, _audio, **options):
                vue["language"] = options.get("language")
                return iter(()), None

        transcripteur = adaptateur.TranscripteurFasterWhisper.__new__(
            adaptateur.TranscripteurFasterWhisper)
        monkeypatch.setattr(transcripteur, "_charger", lambda: FauxModele(), raising=False)
        transcripteur.transcrire(Path("essai.wav"), langue, "")
        return vue["language"]

    def test_une_langue_donnee_est_transmise(self, monkeypatch):
        assert self._langue_recue(monkeypatch, "es") == "es"

    def test_une_langue_vide_devient_none(self, monkeypatch):
        """La chaîne « auto » serait refusée : c'est l'absence qui déclenche
        la détection."""
        assert self._langue_recue(monkeypatch, "") is None
