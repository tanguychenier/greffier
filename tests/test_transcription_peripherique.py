"""Ce que fait la transcription quand la carte graphique se dérobe.

« auto » retient la carte dès qu'il en voit une, sans vérifier que les
bibliothèques CUDA l'accompagnent — le cas ordinaire sous Linux, où rien ne les
installe. Le modèle se charge alors sans broncher, puis le calcul échoue au
premier bloc audio : sans repli, une réunion entière est perdue au moment
précis où elle allait être transcrite.
"""

from pathlib import Path

import pytest

from greffier.adaptateurs.transcription_faster_whisper import TranscripteurFasterWhisper


class FauxSegment:
    def __init__(self, texte: str) -> None:
        self.start = 0.0
        self.end = 1.0
        self.text = texte


class TestRepliSurLeProcesseur:
    def _transcripteur(self, monkeypatch, refuse):
        """Un modèle qui échoue là où échoue une carte sans cuBLAS.

        L'échec ne survient ni à la construction ni à l'appel, mais au parcours
        des segments : ils sont un générateur, et c'est en le parcourant que le
        calcul a lieu. Un double qui échouerait plus tôt éprouverait un cas qui
        n'arrive pas.
        """
        demandes: list[str] = []

        class FauxModele:
            def __init__(self, peripherique: str) -> None:
                self.peripherique = peripherique

            def transcribe(self, _audio, **_options):
                def segments():
                    if self.peripherique in refuse:
                        raise RuntimeError("Library libcublas.so.12 is not found")
                    yield FauxSegment("Bonjour à tous")

                return segments(), None

        transcripteur = TranscripteurFasterWhisper()

        def charger():
            demandes.append(transcripteur.peripherique)
            return FauxModele(transcripteur.peripherique)

        monkeypatch.setattr(transcripteur, "_charger", charger, raising=False)
        return transcripteur, demandes

    def test_le_processeur_prend_le_relais(self, monkeypatch):
        transcripteur, demandes = self._transcripteur(monkeypatch, refuse={"auto"})

        repliques = transcripteur.transcrire(Path("reunion.wav"), "fr", "")

        assert [replique.texte for replique in repliques] == ["Bonjour à tous"]
        assert demandes == ["auto", "cpu"]

    def test_le_modele_est_recharge_pour_le_processeur(self, monkeypatch):
        """Le modèle chargé porte la carte : le garder rejouerait la panne."""
        transcripteur, _ = self._transcripteur(monkeypatch, refuse={"auto"})

        transcripteur.transcrire(Path("reunion.wav"), "fr", "")

        assert transcripteur.peripherique == "cpu"

    def test_une_panne_du_processeur_n_est_pas_masquee(self, monkeypatch):
        """Sinon le repli tournerait en rond et cacherait la vraie cause."""
        transcripteur, demandes = self._transcripteur(monkeypatch, refuse={"auto", "cpu"})

        with pytest.raises(RuntimeError):
            transcripteur.transcrire(Path("reunion.wav"), "fr", "")

        assert demandes == ["auto", "cpu"]
