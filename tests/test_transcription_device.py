"""What the transcription does when the graphics card gives way.

"auto" keeps the card as soon as it sees one, without checking that the CUDA
libraries came with it, which is the ordinary case on Linux where nothing
installs them. The model then loads without a murmur, and the computation fails
on the first block of audio: with no fallback, a whole meeting is lost at the
precise moment it was about to be transcribed.
"""

from pathlib import Path

import pytest

from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.start = 0.0
        self.end = 1.0
        self.text = text


class TestFallingBackToTheProcessor:
    def _transcriber(self, monkeypatch, refuse):
        """A model that fails where a card with no cuBLAS fails.

        The failure happens neither on construction nor on the call, but while walking
        the segments: they are a generator, and the computation happens as it is walked.
        A double failing earlier would cover a case that does not occur.
        """
        requests: list[str] = []

        class FakeModel:
            def __init__(self, device: str) -> None:
                self.device = device

            def transcribe(self, _audio, **_options):
                def segments():
                    if self.device in refuse:
                        raise RuntimeError("Library libcublas.so.12 is not found")
                    yield FakeSegment("Bonjour à tous")

                return segments(), None

        transcriber = FasterWhisperTranscriber()

        def load():
            requests.append(transcriber.device)
            return FakeModel(transcriber.device)

        monkeypatch.setattr(transcriber, "_load", load, raising=False)
        return transcriber, requests

    def test_the_processor_takes_over(self, monkeypatch):
        transcriber, requests = self._transcriber(monkeypatch, refuse={"auto"})

        utterances = transcriber.transcribe(Path("reunion.wav"), "fr", "")

        assert [utterance.text for utterance in utterances] == ["Bonjour à tous"]
        assert requests == ["auto", "cpu"]

    def test_the_model_is_reloaded_for_the_processor(self, monkeypatch):
        """Le modèle chargé porte la carte : le garder rejouerait la panne."""
        transcriber, _ = self._transcriber(monkeypatch, refuse={"auto"})

        transcriber.transcribe(Path("reunion.wav"), "fr", "")

        assert transcriber.device == "cpu"

    def test_a_failure_of_the_processor_is_not_hidden(self, monkeypatch):
        """Otherwise the fallback would go round in circles and hide the real cause."""
        transcriber, requests = self._transcriber(monkeypatch, refuse={"auto", "cpu"})

        with pytest.raises(RuntimeError):
            transcriber.transcribe(Path("reunion.wav"), "fr", "")

        assert requests == ["auto", "cpu"]


class TestLeModeleOuvertUneFois:
    """Ouvrir large-v3 prend douze à dix-neuf secondes.

    Plus longtemps que de transcrire quarante secondes de réunion. Le modèle est
    donc gardé pour le processus : celui qu'on ouvre pendant que l'encodeur
    ferme son fichier sert la chaîne qui suit tout de suite après.
    """

    @pytest.fixture
    def ouvertures(self, monkeypatch):
        from greffier.adapters import transcription_faster_whisper as adaptateur

        faites: list[tuple[str, str]] = []
        monkeypatch.setattr(adaptateur, "_OPENED", {})

        class FauxModule:
            def WhisperModel(self, taille, device, compute_type):  # noqa: N802
                faites.append((taille, device))
                return object()

        monkeypatch.setitem(__import__("sys").modules, "faster_whisper", FauxModule())
        monkeypatch.setattr(adaptateur.cuda, "show_to_the_loader", lambda: None)
        return faites

    def test_two_transcribers_share_one_model(self, ouvertures):
        premier = FasterWhisperTranscriber(taille="large-v3", device="cuda")
        second = FasterWhisperTranscriber(taille="large-v3", device="cuda")
        assert premier._load() is second._load()
        assert ouvertures == [("large-v3", "cuda")]

    def test_another_size_opens_its_own(self, ouvertures):
        """Le direct prend un modèle plus léger : ce n'est pas le même."""
        FasterWhisperTranscriber(taille="large-v3", device="cuda")._load()
        FasterWhisperTranscriber(taille="small", device="cuda")._load()
        assert ouvertures == [("large-v3", "cuda"), ("small", "cuda")]

    def test_warming_opens_it_without_transcribing(self, ouvertures):
        FasterWhisperTranscriber(taille="large-v3", device="cuda").warm()
        assert ouvertures == [("large-v3", "cuda")]

    def test_warming_never_raises(self, monkeypatch, ouvertures):
        """Appelé depuis un fil pendant la fermeture : une panne ici ne coûte rien,
        la chaîne rouvrira le modèle et le dira proprement."""
        from greffier.adapters import transcription_faster_whisper as adaptateur

        class QuiRefuse:
            def WhisperModel(self, *_a, **_k):  # noqa: N802
                raise RuntimeError("plus de mémoire sur la carte")

        monkeypatch.setitem(__import__("sys").modules, "faster_whisper", QuiRefuse())
        monkeypatch.setattr(adaptateur, "_OPENED", {})
        FasterWhisperTranscriber(taille="large-v3", device="cuda").warm()

    def test_a_model_that_failed_is_not_handed_out_again(self, monkeypatch, ouvertures):
        """Celui qui a cassé portait la carte : le rendre rejouerait la panne."""
        from greffier.adapters import transcription_faster_whisper as adaptateur

        transcriber = FasterWhisperTranscriber(taille="large-v3", device="cuda")
        transcriber._load()
        assert ("large-v3", "cuda") in adaptateur._OPENED

        def qui_casse(_audio, _language, _seed):
            raise RuntimeError("Library libcublas.so.12 is not found")

        monkeypatch.setattr(transcriber, "_utterances", qui_casse)
        with pytest.raises(RuntimeError):
            transcriber.transcribe(Path("reunion.wav"), "fr", "")
        assert ("large-v3", "cuda") not in adaptateur._OPENED
