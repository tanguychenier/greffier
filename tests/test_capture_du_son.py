"""Comment se juge la capture du son des autres participants sous Linux.

« pactl » n'enregistre rien : il interroge le serveur de son, quand ffmpeg s'y
branche directement par sa prise. Le juger absent revenait à déclarer perdue une
machine parfaitement capable d'enregistrer — PipeWire en marche, mais
« pulseaudio-utils » jamais installé — et à envoyer chercher un paquet inutile.
"""

import pytest

from greffier import diagnostic


@pytest.fixture
def session(monkeypatch, tmp_path):
    """Une session sans « pactl », dont on ouvre ou non la prise du serveur."""
    monkeypatch.setattr(diagnostic, "SYSTEME", "Linux")
    monkeypatch.setattr(diagnostic.shutil, "which", lambda _outil: None)
    monkeypatch.delenv("PULSE_SERVER", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def ouvrir_la_prise(session):
    prise = session / "pulse"
    prise.mkdir()
    (prise / "native").touch()


class TestServeurDeSon:
    def test_la_prise_du_serveur_suffit(self, session):
        ouvrir_la_prise(session)
        assert diagnostic.serveur_de_son_present()

    def test_sans_prise_ni_serveur_il_n_y_a_rien_a_capter(self, session):
        assert not diagnostic.serveur_de_son_present()

    def test_un_serveur_declare_est_cru(self, session, monkeypatch):
        """Un serveur distant ou par socket nommé ne pose aucune prise ici."""
        monkeypatch.setenv("PULSE_SERVER", "tcp:192.168.1.10:4713")
        assert diagnostic.serveur_de_son_present()


class TestConstatDeCapture:
    def test_la_capture_est_annoncee_possible(self, session):
        ouvrir_la_prise(session)
        constat = diagnostic.capture_systeme()
        assert constat.present
        assert "pactl" not in constat.detail

    def test_le_micro_reste_trouve_par_le_serveur_de_son(self, session, monkeypatch):
        """Un poste sans /proc/asound — un conteneur — mais avec un serveur."""
        monkeypatch.setattr(diagnostic.Path, "exists", lambda self: False)
        monkeypatch.setattr(diagnostic, "serveur_de_son_present", lambda: True)
        assert diagnostic.micro_present().present
