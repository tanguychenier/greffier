"""Ce que fait la transcription quand la carte graphique se dérobe.

« auto » retient la carte dès qu'il en voit une, sans vérifier que les
bibliothèques CUDA l'accompagnent — le cas ordinaire sous Linux, où rien ne les
installe. Le modèle se charge alors sans broncher, puis le calcul échoue au
premier bloc audio : sans repli, une réunion entière est perdue au moment
précis où elle allait être transcrite.
"""

from pathlib import Path

import pytest

from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.start = 0.0
        self.end = 1.0
        self.text = text


class TestRepliSurLeProcesseur:
    def _transcriber(self, monkeypatch, refuse):
        """Un modèle qui échoue là où échoue une carte sans cuBLAS.

        L'échec ne survient ni à la construction ni à l'appel, mais au parcours
        des segments : ils sont un générateur, et c'est en le parcourant que le
        calcul a lieu. Un double qui échouerait plus tôt éprouverait un cas qui
        n'arrive pas.
        """
        requests: list[str] = []

        class FakeModel:
            def __init__(self, peripherique: str) -> None:
                self.peripherique = peripherique

            def transcribe(self, _audio, **_options):
                def segments():
                    if self.peripherique in refuse:
                        raise RuntimeError("Library libcublas.so.12 is not found")
                    yield FakeSegment("Bonjour à tous")

                return segments(), None

        transcriber = FasterWhisperTranscriber()

        def load():
            requests.append(transcriber.peripherique)
            return FakeModel(transcriber.peripherique)

        monkeypatch.setattr(transcriber, "_load", load, raising=False)
        return transcriber, requests

    def test_le_processeur_prend_le_relais(self, monkeypatch):
        transcriber, requests = self._transcriber(monkeypatch, refuse={"auto"})

        utterances = transcriber.transcribe(Path("reunion.wav"), "fr", "")

        assert [utterance.text for utterance in utterances] == ["Bonjour à tous"]
        assert requests == ["auto", "cpu"]

    def test_le_modele_est_recharge_pour_le_processeur(self, monkeypatch):
        """Le modèle chargé porte la carte : le garder rejouerait la panne."""
        transcriber, _ = self._transcriber(monkeypatch, refuse={"auto"})

        transcriber.transcribe(Path("reunion.wav"), "fr", "")

        assert transcriber.peripherique == "cpu"

    def test_une_panne_du_processeur_n_est_pas_masquee(self, monkeypatch):
        """Sinon le repli tournerait en rond et cacherait la vraie cause."""
        transcriber, requests = self._transcriber(monkeypatch, refuse={"auto", "cpu"})

        with pytest.raises(RuntimeError):
            transcriber.transcribe(Path("reunion.wav"), "fr", "")

        assert requests == ["auto", "cpu"]
