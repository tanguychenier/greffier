"""Ce que les deux moteurs reçoivent comme langue.

Le réglage vide veut dire « reconnais-la toi-même ». Les deux moteurs
l'expriment différemment, et se tromper est silencieux : whisper.cpp
transcrirait dans une langue arbitraire, faster-whisper refuserait un code
inconnu — dans les deux cas, une heure après le début de la réunion.
"""

import subprocess
from pathlib import Path

import pytest

from greffier.adapters.transcription_whisper_cpp import TranscripteurWhisperCpp


@pytest.fixture
def model(tmp_path):
    file = tmp_path / "ggml-small.bin"
    file.write_bytes(b"\0" * 16)
    return file


class TestWhisperCpp:
    def _command(self, monkeypatch, model, language):
        vue: dict[str, list[str]] = {}

        def faux_run(command, **_options):
            vue["commande"] = list(command)
            # Un .srt vide suffit : c'est la commande qui est éprouvée.
            Path(command[command.index("-of") + 1] + ".srt").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(
            "greffier.adapters.transcription_whisper_cpp.subprocess.run", faux_run)
        TranscripteurWhisperCpp(model).transcribe(model, language, "")
        return vue["commande"]

    def test_une_langue_donnee_est_transmise(self, monkeypatch, model):
        command = self._command(monkeypatch, model, "en")
        assert command[command.index("-l") + 1] == "en"

    def test_une_langue_vide_devient_auto(self, monkeypatch, model):
        """« -l » attend une valeur : sans elle, l'option suivante serait avalée."""
        command = self._command(monkeypatch, model, "")
        assert command[command.index("-l") + 1] == "auto"


class TestFasterWhisper:
    def _langue_recue(self, monkeypatch, language):
        from greffier.adapters import transcription_faster_whisper as adaptateur

        vue: dict[str, object] = {}

        class FauxModele:
            def transcribe(self, _audio, **options):
                vue["language"] = options.get("language")
                return iter(()), None

        transcriber = adaptateur.TranscripteurFasterWhisper.__new__(
            adaptateur.TranscripteurFasterWhisper)
        monkeypatch.setattr(transcriber, "_load", lambda: FauxModele(), raising=False)
        transcriber.transcribe(Path("essai.wav"), language, "")
        return vue["language"]

    def test_une_langue_donnee_est_transmise(self, monkeypatch):
        assert self._langue_recue(monkeypatch, "es") == "es"

    def test_une_langue_vide_devient_none(self, monkeypatch):
        """La chaîne « auto » serait refusée : c'est l'absence qui déclenche
        la détection."""
        assert self._langue_recue(monkeypatch, "") is None
