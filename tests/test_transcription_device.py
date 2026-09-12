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
