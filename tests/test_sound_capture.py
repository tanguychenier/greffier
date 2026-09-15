"""How the capture of the other attendees' sound is judged on Linux.

« pactl » records nothing: it queries the sound server, where ffmpeg plugs
straight into its socket. Judging it absent amounted to declaring lost a
machine perfectly able to record, PipeWire running, but « pulseaudio-utils »
never installed, and to sending for a useless package.
"""

import pytest

from greffier.adapters import system_diagnostic as diagnostic
from greffier.adapters.audio_ffmpeg import why_unreadable


@pytest.fixture
def session(monkeypatch, tmp_path):
    """A session without « pactl », whose server socket is opened or not."""
    monkeypatch.setattr(diagnostic, "SYSTEM", "Linux")
    monkeypatch.setattr(diagnostic.shutil, "which", lambda _outil: None)
    monkeypatch.delenv("PULSE_SERVER", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def ouvrir_la_prise(session):
    prise = session / "pulse"
    prise.mkdir()
    (prise / "native").touch()


class TestServeurDeSon:
    def test_the_server_socket_is_enough(self, session):
        ouvrir_la_prise(session)
        assert diagnostic.sound_server_present()

    def test_with_neither_socket_nor_server_there_is_nothing_to_capture(self, session):
        assert not diagnostic.sound_server_present()

    def test_a_declared_server_is_believed(self, session, monkeypatch):
        """A remote server or one over a named socket puts no socket here."""
        monkeypatch.setenv("PULSE_SERVER", "tcp:192.168.1.10:4713")
        assert diagnostic.sound_server_present()


class TestConstatDeCapture:
    def test_the_capture_is_announced_as_possible(self, session):
        ouvrir_la_prise(session)
        constat = diagnostic.system_capture()
        assert constat.present
        assert "pactl" not in constat.detail

    def test_the_mic_is_still_found_through_the_sound_server(self, session, monkeypatch):
        """A machine without /proc/asound, a container, but with a server."""
        monkeypatch.setattr(diagnostic.Path, "exists", lambda self: False)
        monkeypatch.setattr(diagnostic, "sound_server_present", lambda: True)
        assert diagnostic.mic_present().present


class TestAFileThatCannotBeARecording:
    """Asked before the models open, which take twenty seconds.

    A file that is not sound used to come back as an `av.error.InvalidDataError`
    and a page of Python traceback, after that wait -- the chain only met the
    file once everything else was in memory.
    """

    def test_sound_is_let_through(self, tmp_path):
        import numpy as np
        import soundfile

        son = tmp_path / "reunion.wav"
        soundfile.write(son, np.zeros(16000, dtype="float32"), 16000)
        assert why_unreadable(son) == ""

    def test_something_that_is_not_sound_says_so_in_french(self, tmp_path):
        faux = tmp_path / "abime.wav"
        faux.write_bytes(b"\x00\x01\x02\x03" * 5000)
        dit = why_unreadable(faux)
        assert "n'est pas un enregistrement lisible" in dit
        assert faux.name in dit

    def test_an_empty_file_says_it_is_empty(self, tmp_path):
        vide = tmp_path / "vide.wav"
        vide.touch()
        assert "est vide" in why_unreadable(vide)

    def test_a_file_that_is_not_there_says_that(self, tmp_path):
        assert "n'existe pas" in why_unreadable(tmp_path / "jamais.wav")

    def test_a_recording_with_no_sound_in_it_is_refused(self, tmp_path):
        import numpy as np
        import soundfile

        muet = tmp_path / "muet.wav"
        soundfile.write(muet, np.zeros(0, dtype="float32"), 16000)
        assert "aucun son" in why_unreadable(muet)
