"""Comment se juge la capture du son des autres participants sous Linux.

« pactl » n'enregistre rien : il interroge le serveur de son, quand ffmpeg s'y
branche directement par sa prise. Le juger absent revenait à déclarer perdue une
machine parfaitement capable d'enregistrer, PipeWire en marche, mais
« pulseaudio-utils » jamais installé, et à envoyer chercher un paquet inutile.
"""

import pytest

from greffier.adapters import system_diagnostic as diagnostic


@pytest.fixture
def session(monkeypatch, tmp_path):
    """Une session sans « pactl », dont on ouvre ou non la prise du serveur."""
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
        """Un serveur distant ou par socket nommé ne pose aucune prise ici."""
        monkeypatch.setenv("PULSE_SERVER", "tcp:192.168.1.10:4713")
        assert diagnostic.sound_server_present()


class TestConstatDeCapture:
    def test_the_capture_is_announced_as_possible(self, session):
        ouvrir_la_prise(session)
        constat = diagnostic.system_capture()
        assert constat.present
        assert "pactl" not in constat.detail

    def test_the_mic_is_still_found_through_the_sound_server(self, session, monkeypatch):
        """Un poste sans /proc/asound, un conteneur, mais avec un serveur."""
        monkeypatch.setattr(diagnostic.Path, "exists", lambda self: False)
        monkeypatch.setattr(diagnostic, "sound_server_present", lambda: True)
        assert diagnostic.mic_present().present
