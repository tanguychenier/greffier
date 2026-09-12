"""The assistant's voice, on all three systems, without owning three.

Nobody has a Mac, a Linux machine and a Windows machine to hand. The detected
system is forced and the command built is checked: that is where the mistakes
live which only show up once you are there.
"""

from types import SimpleNamespace

import pytest

from greffier.adapters import voice_neural, voice_system
from greffier.adapters.voice_neural import clean, sentences


class TestCuttingTheRemarkIntoPieces:
    def test_it_starts_speaking_on_the_first_sentence(self):
        """Generating the whole remark before opening its mouth makes one wait for all
        of it. Generating the first while it is being spoken is the latency of the
        first sentence alone.
        """
        assert sentences("Bonjour. Je suis Lucie. J'écoute.") == [
            "Bonjour.", "Je suis Lucie.", "J'écoute."]

    def test_too_long_a_sentence_is_cut_on_its_commas(self):
        long = ", ".join(["un segment de texte assez long"] * 12) + "."
        chunks = sentences(long, maximum=100)
        assert len(chunks) > 1
        assert all(len(m) <= 120 for m in chunks)

    def test_the_dashes_become_commas(self):
        """They have no phoneme: the model flags them one by one and skips them."""
        assert clean("Bonjour — je suis là") == "Bonjour, je suis là"
        assert "—" not in clean("un — deux – trois-quatre")

    def test_an_empty_remark_produces_nothing(self):
        assert sentences("   ") == []
        assert sentences("") == []


class TestThePlayerOfEachSystem:
    def test_macos_takes_afplay(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Darwin")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "/usr/bin/afplay" if n == "afplay" else None)
        assert voice_neural.player() == ["afplay"]

    def test_linux_takes_whatever_is_there(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "/usr/bin/aplay" if n == "aplay" else None)
        assert voice_neural.player() == ["/usr/bin/aplay"]

    def test_windows_falls_back_to_powershell(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        assert voice_neural.player()[0] == "powershell"

    def test_with_no_player_the_voice_declares_itself_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_neural.shutil, "which", lambda _n: None)
        assert voice_neural.NeuralVoice(tmp_path).available is False


class TestTheVoiceOfTheSystem:
    def test_windows_goes_through_its_built_in_synthesis(self, monkeypatch):
        monkeypatch.setattr(voice_system, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        command = voice_system.SystemVoice(voice=None)._command("bonjour")
        assert command[0] == "powershell"
        assert "System.Speech" in command[-1]
        assert "bonjour" in command[-1]

    def test_an_apostrophe_does_not_break_the_windows_command(self, monkeypatch):
        """A French remark holds one in every sentence.

        The text goes into a PowerShell literal: only single quotes are doubled there,
        and nothing is interpolated.
        """
        monkeypatch.setattr(voice_system, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        command = voice_system.SystemVoice(voice=None)._command("j'arrive")
        assert "j''arrive" in command[-1]

    def test_linux_takes_the_synthesiser_that_is_there(self, monkeypatch):
        monkeypatch.setattr(voice_system, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "/usr/bin/spd-say" if n == "spd-say" else None)
        assert voice_system.SystemVoice(voice=None)._command("salut")[0] == "spd-say"

    def test_linux_with_nothing_does_not_speak(self, monkeypatch):
        monkeypatch.setattr(voice_system, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_system.shutil, "which", lambda _n: None)
        assert voice_system.SystemVoice(voice=None)._command("salut") == []


class TestChoosingTheVoice:
    def _voice_of(self, monkeypatch, listing):
        monkeypatch.setattr(voice_system, "SYSTEM", "Darwin")
        monkeypatch.setattr(voice_system.shutil, "which", lambda _n: "/usr/bin/say")
        monkeypatch.setattr(
            voice_system.subprocess, "run",
            lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=listing))

    def test_an_enhanced_voice_wins(self, monkeypatch):
        self._voice_of(monkeypatch,
                   "Thomas               fr_FR    # Bonjour\n"
                   "Thomas (Premium)     fr_FR    # Bonjour\n")
        assert voice_system.best_voice() == "Thomas (Premium)"
        assert voice_system.better_voice_available()

    def test_failing_that_an_acceptable_compact_one(self, monkeypatch):
        """The "eloquence" voices are a synthesiser from the 1980s.

        Measured elsewhere: a transcription model gets nothing at all out of them. In
        a meeting they are heard for what they are immediately.
        """
        self._voice_of(monkeypatch,
                   "Jacques              fr_FR    # Bonjour\n"
                   "Thomas               fr_FR    # Bonjour\n")
        assert voice_system.best_voice() == "Thomas"
        assert not voice_system.better_voice_available()

    def test_france_before_quebec(self, monkeypatch):
        self._voice_of(monkeypatch,
                   "Amélie (Premium)     fr_CA    # Bonjour\n"
                   "Thomas (Premium)     fr_FR    # Bonjour\n")
        assert voice_system.best_voice() == "Thomas (Premium)"

    def test_no_french_voice_lets_the_system_choose(self, monkeypatch):
        self._voice_of(monkeypatch, "Daniel               en_GB    # Hello\n")
        assert voice_system.best_voice() is None


class TestCuttingTheSoundFromAnotherProcess:
    """The "cut" button is in the window, the voice is in the watch.

    The button wrote a setting the watch only rereads on the next slice, up to
    fifteen seconds later. Measured in a meeting: you press, it keeps speaking, and
    the button looks broken. It was, from the point of view of whoever pressed it.
    """

    def test_the_gag_file_carries_the_player_number(self, tmp_path):
        from greffier.adapters.voice_neural import NeuralVoice

        gag = tmp_path / "parole.pid"
        voice = NeuralVoice(tmp_path, gag=gag)
        voice._publish_the_gag(4242)
        assert gag.read_text() == "4242"

    def test_it_is_deleted_when_the_sound_stops(self, tmp_path):
        """Un numéro qui traîne ferait tuer un processus qui n'est plus le nôtre.

        Sur un système qui recycle les numéros, ce serait n'importe lequel.
        """
        from greffier.adapters.voice_neural import NeuralVoice

        gag = tmp_path / "parole.pid"
        voice = NeuralVoice(tmp_path, gag=gag)
        voice._publish_the_gag(4242)
        voice._publish_the_gag(None)
        assert not gag.exists()

    def test_with_no_gag_nothing_is_written(self, tmp_path):
        """La ligne de commande n'a personne à qui parler."""
        from greffier.adapters.voice_neural import NeuralVoice

        NeuralVoice(tmp_path)._publish_the_gag(4242)
        assert list(tmp_path.iterdir()) == []

    def test_going_quiet_kills_the_named_process(self, tmp_path):
        import subprocess
        import time

        from greffier.adapters.voice_neural import silence

        dormeur = subprocess.Popen(["sleep", "30"])
        gag = tmp_path / "parole.pid"
        gag.write_text(str(dormeur.pid))
        assert silence(gag)
        for _ in range(20):
            if dormeur.poll() is not None:
                break
            time.sleep(0.1)
        assert dormeur.poll() is not None, "le processus n'a pas été coupé"
        assert not gag.exists()

    def test_going_quiet_with_nothing_to_kill_does_not_raise(self, tmp_path):
        """Le cas courant : personne ne parle."""
        from greffier.adapters.voice_neural import silence

        assert not silence(tmp_path / "absent.pid")

    def test_a_dead_number_does_not_raise(self, tmp_path):
        from greffier.adapters.voice_neural import silence

        gag = tmp_path / "parole.pid"
        gag.write_text("999999")
        assert not silence(gag)

    def test_an_unreadable_gag_does_not_raise(self, tmp_path):
        from greffier.adapters.voice_neural import silence

        gag = tmp_path / "parole.pid"
        gag.write_text("ce n'est pas un numéro")
        assert not silence(gag)


class TestOneCutStopsTheWholeRemark:
    """Cutting must silence, not skip a sentence.

    A remark is cut into sentences played one after another. Killing the player of
    the sentence under way let the next one start: it stopped and then resumed,
    which is worse than not stopping at all.
    """

    def _voice_of(self, tmp_path, monkeypatch, retour):
        """A voice whose player returns the exit code wanted."""
        from greffier.adapters import voice_neural

        class ReadBack:
            pid = 4242

            def wait(self):
                return retour

            def poll(self):
                return retour

            def terminate(self):
                ...

            def kill(self):
                ...

        monkeypatch.setattr(voice_neural, "player", lambda: ["afplay"])
        monkeypatch.setattr(voice_neural.subprocess, "Popen",
                            lambda *_a, **_k: ReadBack())
        return voice_neural.NeuralVoice(tmp_path, gag=tmp_path / "p.pid")

    def test_a_player_killed_by_a_signal_stops_what_follows(self, tmp_path, monkeypatch):
        """`afplay` killed by SIGTERM returns -15: that is the button, not an ending."""
        voice = self._voice_of(tmp_path, monkeypatch, retour=-15)
        assert voice._play(tmp_path / "un.wav") is False
        assert voice._interrompu.is_set(), "la suite du propos n'a pas été annulée"

    def test_a_player_that_ends_normally_lets_it_go_on(self, tmp_path,
                                                              monkeypatch):
        voice = self._voice_of(tmp_path, monkeypatch, retour=0)
        assert voice._play(tmp_path / "un.wav") is True
        assert not voice._interrompu.is_set()

    def test_the_gag_is_deleted_either_way(self, tmp_path, monkeypatch):
        for retour in (-15, 0):
            voice = self._voice_of(tmp_path, monkeypatch, retour=retour)
            voice._play(tmp_path / "un.wav")
            assert not (tmp_path / "p.pid").exists()


class TestLaVoixOuverteUneFois:
    """Ouvrir le modèle de voix prend quatre secondes et demie.

    Une voix neuve était construite à chaque question posée en préparation :
    quatre secondes et demie avant chaque réponse, pour une remarque qui se
    prononce ensuite en trois dixièmes. Le moteur est donc gardé pour le
    processus, par dossier, langue et périphérique.
    """

    @pytest.fixture
    def ouvertures(self, monkeypatch, tmp_path):
        from greffier.adapters import voice_neural

        faites: list[str] = []
        monkeypatch.setattr(voice_neural, "_OPENED", {})
        monkeypatch.setattr(
            voice_neural.NeuralVoice, "_open",
            lambda self, where: faites.append(where) or object(),
        )
        (tmp_path / "tokens.txt").touch()
        (tmp_path / "fr_FR-upmc-medium.onnx").touch()
        return faites, tmp_path

    def test_two_questions_open_it_once(self, ouvertures):
        from greffier.adapters.voice_neural import NeuralVoice

        faites, dossier = ouvertures
        premiere = NeuralVoice(dossier, device="cpu")
        seconde = NeuralVoice(dossier, device="cpu")
        assert premiere._load() is seconde._load()
        assert faites == ["cpu"]

    def test_another_language_opens_its_own(self, ouvertures):
        """Une voix anglaise n'est pas la voix française."""
        from greffier.adapters.voice_neural import NeuralVoice

        faites, dossier = ouvertures
        NeuralVoice(dossier, language="fr", device="cpu")._load()
        NeuralVoice(dossier, language="en", device="cpu")._load()
        assert len(faites) == 2

    def test_warming_opens_it_without_saying_anything(self, ouvertures):
        from greffier.adapters.voice_neural import NeuralVoice

        faites, dossier = ouvertures
        NeuralVoice(dossier, device="cpu").warm()
        assert faites == ["cpu"]

    def test_warming_never_raises(self, monkeypatch, ouvertures):
        """Appelée depuis un fil pendant qu'on parle : une panne ici ne coûte rien."""
        from greffier.adapters import voice_neural

        _, dossier = ouvertures

        def qui_refuse(_self, _where):
            raise RuntimeError("modèle illisible")

        monkeypatch.setattr(voice_neural.NeuralVoice, "_open", qui_refuse)
        voice_neural.NeuralVoice(dossier, device="cpu").warm()
