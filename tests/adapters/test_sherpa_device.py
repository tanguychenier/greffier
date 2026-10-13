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

import numpy as np
import pytest
import soundfile as sf

from greffier.adapters import cuda
from greffier.adapters import diarisation_sherpa as cutting
from greffier.adapters import voice_neural as voice
from greffier.adapters import voiceprints_titanet as voiceprints


@pytest.fixture
def models(tmp_path):
    for name in ("segmentation.onnx", "empreintes.onnx"):
        (tmp_path / name).touch()
    return tmp_path


@pytest.fixture
def without_card(monkeypatch):
    monkeypatch.setattr(cuda, "a_card_answers", lambda: False)


@pytest.fixture
def with_card(monkeypatch):
    monkeypatch.setattr(cuda, "a_card_answers", lambda: True)


@pytest.fixture
def loader(monkeypatch):
    """Counts the times the CUDA libraries are shown to the loader."""
    calls = []
    monkeypatch.setattr(cuda, "show_to_the_loader", lambda: calls.append(1))
    return calls


class TestTheSegmentation:
    @pytest.mark.usefixtures("with_card")
    def test_the_card_is_taken_when_there_is_one(self, models, loader):
        tool = cutting.SherpaDiariser(
            models / "segmentation.onnx", models / "empreintes.onnx"
        )
        assert tool._device() == "cuda"
        assert loader == [1], "les bibliothèques doivent être chargées avant le modèle"

    @pytest.mark.usefixtures("without_card")
    def test_the_processor_when_no_card_answers(self, models, loader):
        tool = cutting.SherpaDiariser(
            models / "segmentation.onnx", models / "empreintes.onnx"
        )
        assert tool._device() == "cpu"
        assert loader == [], "rien à charger sans carte"

    @pytest.mark.usefixtures("with_card")
    def test_the_setting_wins_over_the_card(self, models, loader):
        """A card taken by something else is refused in the settings file."""
        tool = cutting.SherpaDiariser(
            models / "segmentation.onnx", models / "empreintes.onnx", device="cpu"
        )
        assert tool._device() == "cpu"
        assert loader == []

    def test_a_missing_model_is_said_before_anything_else(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            cutting.SherpaDiariser(tmp_path / "absent.onnx", tmp_path / "absent.onnx")


class TestTheVoiceprints:
    @pytest.fixture
    def silent_sherpa(self, monkeypatch):
        """The model weighs a hundred megabytes: here only what is passed to it is kept."""
        received_ones: list[dict] = []
        monkeypatch.setattr(voiceprints, "_OPENED", {})

        monkeypatch.setattr(
            voiceprints,
            "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=lambda **options: received_ones.append(options),
                SpeakerEmbeddingExtractor=lambda _config: object(),
            ),
        )
        return received_ones

    @pytest.mark.usefixtures("with_card")
    def test_the_card_reaches_the_model(self, models, loader, silent_sherpa):
        tool = voiceprints.TitaNetExtractor(models / "empreintes.onnx")
        assert tool.device == "cuda"
        assert tool._extractor is not None
        assert silent_sherpa[0]["provider"] == "cuda"
        assert loader == [1]

    @pytest.mark.usefixtures("without_card")
    def test_the_processor_reaches_the_model(self, models, loader, silent_sherpa):
        tool = voiceprints.TitaNetExtractor(models / "empreintes.onnx")
        assert tool._extractor is not None
        assert silent_sherpa[0]["provider"] == "cpu"
        assert tool.device == "cpu"
        assert loader == []

    @pytest.mark.usefixtures("with_card", "loader")
    def test_the_setting_wins_over_the_card(self, models, silent_sherpa):
        tool = voiceprints.TitaNetExtractor(models / "empreintes.onnx", device="cpu")
        assert tool._extractor is not None
        assert silent_sherpa[0]["provider"] == "cpu"

    @pytest.mark.usefixtures("without_card", "loader")
    def test_the_model_keeps_its_threads(self, models, silent_sherpa):
        """Choosing the card must not lose the choice of threads."""
        tool = voiceprints.TitaNetExtractor(models / "empreintes.onnx")
        assert tool._extractor is not None
        assert silent_sherpa[0]["num_threads"] >= 1

    @pytest.mark.usefixtures("without_card")
    def test_naming_a_second_voice_opens_nothing(self, models, silent_sherpa):
        """A hundred megabytes per click on « nommer », that was the previous price."""
        first = voiceprints.TitaNetExtractor(models / "empreintes.onnx")
        second = voiceprints.TitaNetExtractor(models / "empreintes.onnx")
        assert first._extractor is second._extractor
        assert len(silent_sherpa) == 1


class LaVoix:
    """What sherpa receives to make a voice, without loading the 76 MB."""

    def __init__(self, monkeypatch, folder):
        self.received_ones: dict = {}
        monkeypatch.setitem(
            __import__("sys").modules, "sherpa_onnx", self._fake_sherpa()
        )
        (folder / "tokens.txt").touch()
        (folder / "fr_FR-upmc-medium.onnx").touch()
        self.folder = folder

    def _fake_sherpa(self):
        received_ones = self.received_ones

        def model(**options):
            received_ones.update(options)
            return SimpleNamespace(**options)

        return SimpleNamespace(
            OfflineTtsModelConfig=model,
            OfflineTtsVitsModelConfig=SimpleNamespace,
            OfflineTtsKokoroModelConfig=SimpleNamespace,
            OfflineTtsConfig=lambda model: SimpleNamespace(
                model=model, validate=lambda: True
            ),
            OfflineTts=lambda _config: object(),
        )


class TestTheVoice:
    @pytest.mark.usefixtures("with_card")
    def test_the_card_reaches_the_voice(self, tmp_path, monkeypatch, loader):
        bench = LaVoix(monkeypatch, tmp_path)
        voice.NeuralVoice(bench.folder)._load()
        assert bench.received_ones["provider"] == "cuda"
        assert loader == [1]

    @pytest.mark.usefixtures("without_card")
    def test_the_processor_when_no_card_answers(
        self, tmp_path, monkeypatch, loader
    ):
        bench = LaVoix(monkeypatch, tmp_path)
        voice.NeuralVoice(bench.folder)._load()
        assert bench.received_ones["provider"] == "cpu"
        assert loader == []

    @pytest.mark.usefixtures("with_card", "loader")
    def test_the_setting_wins_over_the_card(self, tmp_path, monkeypatch, ):
        bench = LaVoix(monkeypatch, tmp_path)
        voice.NeuralVoice(bench.folder, device="cpu")._load()
        assert bench.received_ones["provider"] == "cpu"

    @pytest.mark.usefixtures("with_card", "loader")
    def test_the_model_is_opened_once(self, tmp_path, monkeypatch, ):
        """Ouvrir le modèle coûte cinq secondes : deux fois serait dix."""
        bench = LaVoix(monkeypatch, tmp_path)
        speaking_one = voice.NeuralVoice(bench.folder)
        assert speaking_one._load() is speaking_one._load()


@pytest.mark.usefixtures("loader")
@pytest.mark.parametrize("device", ["cuda", "cpu"])
def test_diarisation_recovers_only_from_a_gpu_initialisation_failure(
    models, monkeypatch, tmp_path, device,
):
    monkeypatch.setattr(cuda, "a_card_is_usable", lambda: True)
    attempts = []
    engine = SimpleNamespace(
        sample_rate=16000,
        process=lambda _: SimpleNamespace(sort_by_start_time=lambda: [
            SimpleNamespace(start=0, end=2, speaker=0),
        ]),
    )

    def open_model(config):
        provider = config.segmentation.provider
        attempts.append((provider, config.embedding.provider))
        if len(attempts) == 1:
            raise RuntimeError("allocation failed")
        return engine

    monkeypatch.setattr(cutting.sherpa_onnx, "OfflineSpeakerDiarization", open_model)
    tool = cutting.SherpaDiariser(
        models / "segmentation.onnx", models / "empreintes.onnx", device=device,
    )
    audio = tmp_path / "silence.wav"
    sf.write(audio, np.zeros(32000, dtype="float32"), 16000)
    if device == "cpu":
        with pytest.raises(RuntimeError, match="allocation failed"):
            tool.segment(audio, None)
        assert attempts == [("cpu", "cpu")]
    else:
        assert tool.segment(audio, None)[0].span.end == 2
        assert attempts == [("cuda", "cuda"), ("cpu", "cpu")]
        assert tool.device == "cpu" and tool.fell_back_because == "allocation failed"


@pytest.mark.usefixtures("loader")
@pytest.mark.parametrize("device", ["cuda", "cpu"])
def test_voiceprints_recover_only_from_a_gpu_initialisation_failure(
    models, monkeypatch, device,
):
    monkeypatch.setattr(cuda, "a_card_is_usable", lambda: True)
    monkeypatch.setattr(voiceprints, "_OPENED", {})
    attempts = []
    engine = object()

    def open_model(config):
        attempts.append(config.provider)
        if len(attempts) == 1:
            raise RuntimeError("allocation failed")
        return engine

    monkeypatch.setattr(voiceprints.sherpa_onnx, "SpeakerEmbeddingExtractor", open_model)
    tool = voiceprints.TitaNetExtractor(models / "empreintes.onnx", device=device)
    if device == "cpu":
        with pytest.raises(RuntimeError, match="allocation failed"):
            _ = tool._extractor
        assert attempts == ["cpu"]
    else:
        assert tool._extractor is engine
        assert tool._extractor is engine
        second = voiceprints.TitaNetExtractor(models / "empreintes.onnx", device="cpu")
        assert second._extractor is engine
        assert attempts == ["cuda", "cpu"]
        assert tool.device == "cpu" and tool.fell_back_because == "allocation failed"
