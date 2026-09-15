"""What the segmentation, the voiceprints and the voice run on.

The segmentation runs the voiceprint model on every excerpt, and that model
is large. Measured on a 40.7 s meeting, same models and same turns returned:
43 s on the processor, 5.8 s on the card. It is by far the first cost item of
the processing, ahead of the transcription, though done by a much heavier
model. These tests check that the choice reaches the models, and that the
CUDA libraries are only shown to the loader when they are about to be used.

The voice follows the same rule: 2.43 s to speak a five-second remark on the
processor, 0.28 s on the card. That is the difference between a conversation
and a form.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from greffier.adapters import cuda
from greffier.adapters import diarisation_sherpa as decoupage
from greffier.adapters import voice_neural as voix
from greffier.adapters import voiceprints_titanet as empreintes


@pytest.fixture
def modeles(tmp_path):
    for nom in ("segmentation.onnx", "empreintes.onnx"):
        (tmp_path / nom).touch()
    return tmp_path


@pytest.fixture
def sans_carte(monkeypatch):
    monkeypatch.setattr(cuda, "a_card_answers", lambda: False)


@pytest.fixture
def avec_carte(monkeypatch):
    monkeypatch.setattr(cuda, "a_card_answers", lambda: True)


@pytest.fixture
def chargeur(monkeypatch):
    """Counts the times the CUDA libraries are shown to the loader."""
    appels = []
    monkeypatch.setattr(cuda, "show_to_the_loader", lambda: appels.append(1))
    return appels


class TestLeDecoupage:
    def test_the_card_is_taken_when_there_is_one(self, modeles, avec_carte, chargeur):
        outil = decoupage.SherpaDiariser(
            modeles / "segmentation.onnx", modeles / "empreintes.onnx"
        )
        assert outil._device() == "cuda"
        assert chargeur == [1], "les bibliothèques doivent être chargées avant le modèle"

    def test_the_processor_when_no_card_answers(self, modeles, sans_carte, chargeur):
        outil = decoupage.SherpaDiariser(
            modeles / "segmentation.onnx", modeles / "empreintes.onnx"
        )
        assert outil._device() == "cpu"
        assert chargeur == [], "rien à charger sans carte"

    def test_the_setting_wins_over_the_card(self, modeles, avec_carte, chargeur):
        """A card taken by something else is refused in the settings file."""
        outil = decoupage.SherpaDiariser(
            modeles / "segmentation.onnx", modeles / "empreintes.onnx", device="cpu"
        )
        assert outil._device() == "cpu"
        assert chargeur == []

    def test_a_missing_model_is_said_before_anything_else(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            decoupage.SherpaDiariser(tmp_path / "absent.onnx", tmp_path / "absent.onnx")


class TestLesEmpreintes:
    @pytest.fixture
    def sherpa_muet(self, monkeypatch):
        """The model weighs a hundred megabytes: here only what is passed to it is kept."""
        recus: list[dict] = []
        monkeypatch.setattr(empreintes, "_OPENED", {})

        monkeypatch.setattr(
            empreintes,
            "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=lambda **options: recus.append(options),
                SpeakerEmbeddingExtractor=lambda _config: object(),
            ),
        )
        return recus

    def test_the_card_reaches_the_model(self, modeles, avec_carte, chargeur, sherpa_muet):
        outil = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert outil.device == "cuda"
        assert outil._extractor is not None
        assert sherpa_muet[0]["provider"] == "cuda"
        assert chargeur == [1]

    def test_the_processor_reaches_the_model(self, modeles, sans_carte, chargeur, sherpa_muet):
        outil = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert outil._extractor is not None
        assert sherpa_muet[0]["provider"] == "cpu"
        assert outil.device == "cpu"
        assert chargeur == []

    def test_the_setting_wins_over_the_card(self, modeles, avec_carte, chargeur, sherpa_muet):
        outil = empreintes.TitaNetExtractor(modeles / "empreintes.onnx", device="cpu")
        assert outil._extractor is not None
        assert sherpa_muet[0]["provider"] == "cpu"

    def test_the_model_keeps_its_threads(self, modeles, sans_carte, chargeur, sherpa_muet):
        """Choosing the card must not lose the choice of threads."""
        outil = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert outil._extractor is not None
        assert sherpa_muet[0]["num_threads"] >= 1

    def test_naming_a_second_voice_opens_nothing(self, modeles, sans_carte, sherpa_muet):
        """A hundred megabytes per click on « nommer », that was the previous price."""
        premier = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        second = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert premier._extractor is second._extractor
        assert len(sherpa_muet) == 1


class LaVoix:
    """What sherpa receives to make a voice, without loading the 76 MB."""

    def __init__(self, monkeypatch, dossier):
        self.recus: dict = {}
        monkeypatch.setitem(
            __import__("sys").modules, "sherpa_onnx", self._faux_sherpa()
        )
        (dossier / "tokens.txt").touch()
        (dossier / "fr_FR-upmc-medium.onnx").touch()
        self.dossier = dossier

    def _faux_sherpa(self):
        recus = self.recus

        def modele(**options):
            recus.update(options)
            return SimpleNamespace(**options)

        return SimpleNamespace(
            OfflineTtsModelConfig=modele,
            OfflineTtsVitsModelConfig=lambda **o: SimpleNamespace(**o),
            OfflineTtsKokoroModelConfig=lambda **o: SimpleNamespace(**o),
            OfflineTtsConfig=lambda model: SimpleNamespace(
                model=model, validate=lambda: True
            ),
            OfflineTts=lambda _config: object(),
        )


class TestLaVoix:
    def test_the_card_reaches_the_voice(self, tmp_path, monkeypatch, avec_carte, chargeur):
        banc = LaVoix(monkeypatch, tmp_path)
        voix.NeuralVoice(banc.dossier)._load()
        assert banc.recus["provider"] == "cuda"
        assert chargeur == [1]

    def test_the_processor_when_no_card_answers(
        self, tmp_path, monkeypatch, sans_carte, chargeur
    ):
        banc = LaVoix(monkeypatch, tmp_path)
        voix.NeuralVoice(banc.dossier)._load()
        assert banc.recus["provider"] == "cpu"
        assert chargeur == []

    def test_the_setting_wins_over_the_card(self, tmp_path, monkeypatch, avec_carte, chargeur):
        banc = LaVoix(monkeypatch, tmp_path)
        voix.NeuralVoice(banc.dossier, device="cpu")._load()
        assert banc.recus["provider"] == "cpu"

    def test_the_model_is_opened_once(self, tmp_path, monkeypatch, avec_carte, chargeur):
        """Ouvrir le modèle coûte cinq secondes : deux fois serait dix."""
        banc = LaVoix(monkeypatch, tmp_path)
        parlante = voix.NeuralVoice(banc.dossier)
        assert parlante._load() is parlante._load()
