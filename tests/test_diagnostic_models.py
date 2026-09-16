"""What the diagnostic must notice before a meeting starts.

It listed ffmpeg, the microphone and the disk, and said "everything is in
place" on a machine that could not transcribe a word: the models weigh 1.7 GB
and are downloaded separately, so their absence is the likeliest reason for a
meeting to produce nothing. Silence there is the worst possible answer.
"""

import re

import pytest

from greffier.adapters import system_diagnostic as diagnostic


@pytest.fixture
def data(tmp_path):
    (tmp_path / "modeles").mkdir()
    return tmp_path


def poser(data, model, size=None):
    """Writes a model file heavy enough to count as present."""
    path = data / "modeles" / model.folder / model.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * (size if size is not None else model.minimum))


class TestTheModelsAreLookedAt:
    def test_a_bare_machine_is_told_what_is_missing(self, data):
        the_reading = diagnostic.models_present(data)
        assert not the_reading.present
        assert "manquant" in the_reading.detail
        assert the_reading.remedy, "il dit quoi faire, pas seulement ce qui manque"

    def test_the_download_weight_is_announced(self, data):
        """In whichever unit: the engines differ per system, and so does the
        weight, 1.7 GB with whisper.cpp, 71 MB where faster-whisper carries
        the transcription model itself."""
        assert re.search(r"\d+([.,]\d+)? (Mo|Go) à télécharger",
                         diagnostic.models_present(data).detail)

    def test_a_missing_required_model_blocks(self, data):
        assert diagnostic.models_present(data).is_blocking

    def test_a_full_machine_says_so(self, data, monkeypatch):
        from greffier.adapters import model_files

        monkeypatch.setattr(model_files, "missing", lambda _folder, _engine="": [])
        the_reading = diagnostic.models_present(data)
        assert the_reading.present
        assert "en place" in the_reading.detail

    def test_the_engine_of_the_system_is_the_one_looked_up(self, data, monkeypatch):
        """whisper.cpp on macOS, faster-whisper elsewhere: they need different
        files, and asking for the wrong ones reports a machine unusable."""
        from greffier.adapters import model_files

        seen = []
        monkeypatch.setattr(model_files, "missing",
                            lambda folder, engine="": seen.append(engine) or [])
        monkeypatch.setattr(diagnostic, "SYSTEM", "Linux")
        diagnostic.models_present(data)
        assert seen == ["faster-whisper"]


class TestTheVoiceBankIsLookedAt:
    def test_an_absent_bank_is_not_a_fault(self, tmp_path):
        """A first meeting has no bank: the voices are named during it."""
        the_reading = diagnostic.known_voices(tmp_path)
        assert the_reading.present
        assert "vide" in the_reading.detail

    def test_the_number_of_known_people_is_said(self, tmp_path, monkeypatch):
        from greffier.adapters import voice_bank_files
        from greffier.domain.models import Person

        (tmp_path / "banque-de-voix").mkdir()
        monkeypatch.setattr(
            voice_bank_files.FileVoiceBank, "people",
            lambda _self: [Person(name="Lise", voiceprints=[]),
                           Person(name="Pascal", voiceprints=[])],
        )
        assert "2 personne" in diagnostic.known_voices(tmp_path).detail

    def test_an_unreadable_bank_is_reported_rather_than_raised(
        self, tmp_path, monkeypatch
    ):
        from greffier.adapters import voice_bank_files

        (tmp_path / "banque-de-voix").mkdir()

        def refuse(_self):
            raise OSError("Permission denied")

        monkeypatch.setattr(voice_bank_files.FileVoiceBank, "people", refuse)
        the_reading = diagnostic.known_voices(tmp_path)
        assert not the_reading.present
        assert "Permission denied" in the_reading.detail


class TestTheWholeReading:
    def test_the_two_readings_join_the_others(self, data, monkeypatch):
        from greffier.adapters import model_files

        monkeypatch.setattr(model_files, "missing", lambda _folder, _engine="": [])
        the_names = [c.name for c in diagnostic.examine(data).readings]
        assert "Modèles" in the_names and "Banque de voix" in the_names

    def test_missing_models_make_the_machine_not_ready(self, data):
        assert not diagnostic.examine(data).ready
