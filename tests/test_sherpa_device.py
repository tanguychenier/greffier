"""Sur quoi tournent le découpage en tours de parole et les empreintes.

Le découpage fait tourner le modèle d'empreintes sur chaque extrait, et ce
modèle est gros. Mesuré sur une réunion de 40,7 s, mêmes modèles et mêmes tours
rendus : 43 s sur le processeur, 5,8 s sur la carte. C'est, de loin, le premier
poste de dépense du traitement — devant la transcription, pourtant faite par un
modèle bien plus lourd. Ces tests vérifient que le choix arrive jusqu'aux
modèles, et que les bibliothèques CUDA ne sont montrées au chargeur que
lorsqu'on va s'en servir.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from greffier.adapters import cuda
from greffier.adapters import diarisation_sherpa as decoupage
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
    """Compte les fois où les bibliothèques CUDA sont montrées au chargeur."""
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
        """Une carte prise par autre chose se refuse dans le fichier de réglages."""
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
        """Le modèle pèse cent mégaoctets : ici on ne garde que ce qu'on lui passe."""
        recus = {}

        def config(**options):
            recus.update(options)
            return SimpleNamespace(**options)

        monkeypatch.setattr(
            empreintes,
            "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=config,
                SpeakerEmbeddingExtractor=lambda _config: object(),
            ),
        )
        return recus

    def test_the_card_reaches_the_model(self, modeles, avec_carte, chargeur, sherpa_muet):
        outil = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert sherpa_muet["provider"] == "cuda"
        assert outil.device == "cuda"
        assert chargeur == [1]

    def test_the_processor_reaches_the_model(self, modeles, sans_carte, chargeur, sherpa_muet):
        outil = empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert sherpa_muet["provider"] == "cpu"
        assert outil.device == "cpu"
        assert chargeur == []

    def test_the_setting_wins_over_the_card(self, modeles, avec_carte, chargeur, sherpa_muet):
        empreintes.TitaNetExtractor(modeles / "empreintes.onnx", device="cpu")
        assert sherpa_muet["provider"] == "cpu"

    def test_the_model_keeps_its_threads(self, modeles, sans_carte, chargeur, sherpa_muet):
        """Le choix de la carte ne doit pas faire perdre celui des fils."""
        empreintes.TitaNetExtractor(modeles / "empreintes.onnx")
        assert sherpa_muet["num_threads"] >= 1

