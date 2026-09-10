"""What the diagnostic must notice before a meeting starts.

It listed ffmpeg, the microphone and the disk, and said "everything is in
place" on a machine that could not transcribe a word: the models weigh 1.7 GB
and are downloaded separately, so their absence is the likeliest reason for a
meeting to produce nothing. Silence there is the worst possible answer.
"""

import pytest

from greffier.adapters import system_diagnostic as diagnostic


@pytest.fixture
def data(tmp_path):
    (tmp_path / "modeles").mkdir()
    return tmp_path


def poser(data, model, taille=None):
    """Writes a model file heavy enough to count as present."""
    chemin = data / "modeles" / model.folder / model.name
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(b"0" * (taille if taille is not None else model.minimum))


class TestTheModelsAreLookedAt:
    def test_a_bare_machine_is_told_what_is_missing(self, data):
        constat = diagnostic.models_present(data)
        assert not constat.present
        assert "manquant" in constat.detail
        assert constat.remede, "il dit quoi faire, pas seulement ce qui manque"

    def test_the_download_weight_is_announced(self, data):
        assert "Go" in diagnostic.models_present(data).detail

    def test_a_missing_required_model_blocks(self, data):
        assert diagnostic.models_present(data).bloquant

    def test_a_full_machine_says_so(self, data, monkeypatch):
        from greffier.adapters import model_files

        monkeypatch.setattr(model_files, "missing", lambda _folder, _engine="": [])
        constat = diagnostic.models_present(data)
        assert constat.present
        assert "en place" in constat.detail

    def test_the_engine_of_the_system_is_the_one_looked_up(self, data, monkeypatch):
        """whisper.cpp on macOS, faster-whisper elsewhere: they need different
        files, and asking for the wrong ones reports a machine unusable."""
        from greffier.adapters import model_files

        vus = []
        monkeypatch.setattr(model_files, "missing",
                            lambda folder, engine="": vus.append(engine) or [])
        monkeypatch.setattr(diagnostic, "SYSTEM", "Linux")
        diagnostic.models_present(data)
        assert vus == ["faster-whisper"]


class TestTheVoiceBankIsLookedAt:
    def test_an_absent_bank_is_not_a_fault(self, tmp_path):
        """A first meeting has no bank: the voices are named during it."""
        constat = diagnostic.known_voices(tmp_path)
        assert constat.present
        assert "vide" in constat.detail

    def test_the_number_of_known_people_is_said(self, tmp_path, monkeypatch):
        from greffier.adapters import voice_bank_files
        from greffier.domain.models import Person

        (tmp_path / "banque-de-voix").mkdir()
        monkeypatch.setattr(
            voice_bank_files.FileVoiceBank, "people",
            lambda _self: [Person(name="Laura", voiceprints=[]),
                           Person(name="Paul", voiceprints=[])],
        )
        assert "2 personne" in diagnostic.known_voices(tmp_path).detail

    def test_an_unreadable_bank_is_reported_rather_than_raised(
        self, tmp_path, monkeypatch
    ):
        from greffier.adapters import voice_bank_files

        (tmp_path / "banque-de-voix").mkdir()

        def refuser(_self):
            raise OSError("Permission denied")

        monkeypatch.setattr(voice_bank_files.FileVoiceBank, "people", refuser)
        constat = diagnostic.known_voices(tmp_path)
        assert not constat.present
        assert "Permission denied" in constat.detail


class TestTheWholeReading:
    def test_the_two_readings_join_the_others(self, data, monkeypatch):
        from greffier.adapters import model_files

        monkeypatch.setattr(model_files, "missing", lambda _folder, _engine="": [])
        noms = [c.name for c in diagnostic.examine(data).constats]
        assert "Modèles" in noms and "Banque de voix" in noms

    def test_missing_models_make_the_machine_not_ready(self, data):
        assert not diagnostic.examine(data).ready
