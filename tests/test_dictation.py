"""Recording one sentence spoken to the assistant.

Held, never listening: outside a meeting a microphone that opens by itself is a
surveillance device. Pressing is the decision, releasing is the end of the
sentence -- which also spares guessing where a silence means « I have finished ».
"""

from __future__ import annotations

import signal

import pytest

from greffier.adapters.dictation_ffmpeg import Dictation


class FauxProcessus:
    def __init__(self, vivant=True):
        self.signaux: list[int] = []
        self.tue = False
        self._vivant = vivant

    def poll(self):
        return None if self._vivant else 0

    def send_signal(self, numero):
        self.signaux.append(numero)
        self._vivant = False

    def kill(self):
        self.tue = True
        self._vivant = False


@pytest.fixture
def ffmpeg(monkeypatch):
    lances: list[list[str]] = []
    processus = FauxProcessus()
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda commande, **k: lances.append(commande) or processus,
    )
    return lances, processus


class TestFromThePressToTheRelease:
    def test_the_microphone_opens_on_the_press(self, ffmpeg, tmp_path):
        lances, _ = ffmpeg
        Dictation().start(tmp_path / "phrase.wav")
        assert lances and lances[0][0] == "ffmpeg"
        assert str(tmp_path / "phrase.wav") in lances[0]

    def test_it_records_what_the_chain_reads(self, ffmpeg, tmp_path):
        """16 kHz mono: the same take the transcription expects."""
        lances, _ = ffmpeg
        Dictation().start(tmp_path / "phrase.wav")
        assert "16000" in lances[0] and "-ac" in lances[0]

    def test_a_second_press_opens_nothing_more(self, ffmpeg, tmp_path):
        lances, _ = ffmpeg
        dictee = Dictation()
        dictee.start(tmp_path / "une.wav")
        dictee.start(tmp_path / "deux.wav")
        assert len(lances) == 1

    def test_it_stops_with_an_interrupt_never_a_kill(self, ffmpeg, tmp_path):
        """A wav whose header was never written is a file, not a sentence."""
        _, processus = ffmpeg
        dictee = Dictation()
        dictee.start(tmp_path / "phrase.wav")
        (tmp_path / "phrase.wav").write_bytes(b"RIFF" + b"0" * 4000)
        assert dictee.stop() == tmp_path / "phrase.wav"
        assert processus.signaux == [signal.SIGINT] and not processus.tue

    def test_a_key_merely_tapped_produces_nothing(self, ffmpeg, tmp_path):
        """A few dozen bytes are a header and no sound."""
        dictee = Dictation()
        dictee.start(tmp_path / "phrase.wav")
        (tmp_path / "phrase.wav").write_bytes(b"RIFF" + b"0" * 20)
        assert dictee.stop() is None

    def test_releasing_without_pressing_is_not_an_error(self, tmp_path):
        assert Dictation().stop() is None

    def test_a_ceiling_keeps_a_held_key_from_filling_a_disk(self, ffmpeg, tmp_path):
        lances, _ = ffmpeg
        Dictation(maximum=30).start(tmp_path / "phrase.wav")
        assert lances[0][lances[0].index("-t") + 1] == "30"


class TestTheInputPerSystem:
    def test_linux_records_from_pulse(self, monkeypatch, ffmpeg, tmp_path):
        from greffier.adapters import dictation_ffmpeg

        monkeypatch.setattr(dictation_ffmpeg, "SYSTEM", "Linux")
        lances, _ = ffmpeg
        Dictation(device="mon-micro").start(tmp_path / "p.wav")
        assert "pulse" in lances[0] and "mon-micro" in lances[0]

    def test_macos_records_from_avfoundation(self, monkeypatch, ffmpeg, tmp_path):
        from greffier.adapters import dictation_ffmpeg

        monkeypatch.setattr(dictation_ffmpeg, "SYSTEM", "Darwin")
        lances, _ = ffmpeg
        Dictation(device="1").start(tmp_path / "p.wav")
        assert "avfoundation" in lances[0] and ":1" in lances[0]

    def test_windows_records_from_dshow(self, monkeypatch, ffmpeg, tmp_path):
        from greffier.adapters import dictation_ffmpeg

        monkeypatch.setattr(dictation_ffmpeg, "SYSTEM", "Windows")
        lances, _ = ffmpeg
        Dictation(device="Micro").start(tmp_path / "p.wav")
        assert "dshow" in lances[0] and "audio=Micro" in lances[0]
