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
        """A lingering number would kill a process that is no longer ours.

        On a system that recycles numbers, it would be any process at all.
        """
        from greffier.adapters.voice_neural import NeuralVoice

        gag = tmp_path / "parole.pid"
        voice = NeuralVoice(tmp_path, gag=gag)
        voice._publish_the_gag(4242)
        voice._publish_the_gag(None)
        assert not gag.exists()

    def test_with_no_gag_nothing_is_written(self, tmp_path):
        """The command line has nobody to talk to."""
        from greffier.adapters.voice_neural import NeuralVoice

        NeuralVoice(tmp_path)._publish_the_gag(4242)
        assert list(tmp_path.iterdir()) == []

    def test_going_quiet_kills_the_named_process(self, tmp_path):
        import subprocess
        import time

        from greffier.adapters.voice_neural import silence

        sleeper = subprocess.Popen(["sleep", "30"])
        gag = tmp_path / "parole.pid"
        gag.write_text(str(sleeper.pid))
        assert silence(gag)
        for _ in range(20):
            if sleeper.poll() is not None:
                break
            time.sleep(0.1)
        assert sleeper.poll() is not None, "le processus n'a pas été coupé"
        assert not gag.exists()

    def test_going_quiet_with_nothing_to_kill_does_not_raise(self, tmp_path):
        """The usual case: nobody is speaking."""
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

    def _voice_of(self, tmp_path, monkeypatch, return_value):
        """A voice whose player returns the exit code wanted."""
        from greffier.adapters import voice_neural

        class ReadBack:
            pid = 4242

            def wait(self):
                return return_value

            def poll(self):
                return return_value

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
        voice = self._voice_of(tmp_path, monkeypatch, return_value=-15)
        assert voice._play(tmp_path / "un.wav") is False
        assert voice._interrupted.is_set(), "la suite du propos n'a pas été annulée"

    def test_a_player_that_ends_normally_lets_it_go_on(self, tmp_path,
                                                              monkeypatch):
        voice = self._voice_of(tmp_path, monkeypatch, return_value=0)
        assert voice._play(tmp_path / "un.wav") is True
        assert not voice._interrupted.is_set()

    def test_the_gag_is_deleted_either_way(self, tmp_path, monkeypatch):
        for return_value in (-15, 0):
            voice = self._voice_of(tmp_path, monkeypatch, return_value=return_value)
            voice._play(tmp_path / "un.wav")
            assert not (tmp_path / "p.pid").exists()


class TestTheVoiceOpenedOnce:
    """Opening the voice model takes four and a half seconds.

    A new voice was built at every question asked in preparation: four and a
    half seconds before every answer, for a remark then spoken in three
    tenths. The engine is therefore kept for the process, per folder,
    language and device.
    """

    @pytest.fixture
    def openings(self, monkeypatch, tmp_path):
        from greffier.adapters import voice_neural

        done_ones: list[str] = []
        monkeypatch.setattr(voice_neural, "_OPENED", {})
        monkeypatch.setattr(
            voice_neural.NeuralVoice, "_open",
            lambda self, where: done_ones.append(where) or object(),
        )
        (tmp_path / "tokens.txt").touch()
        (tmp_path / "fr_FR-upmc-medium.onnx").touch()
        return done_ones, tmp_path

    def test_two_questions_open_it_once(self, openings):
        from greffier.adapters.voice_neural import NeuralVoice

        done_ones, folder = openings
        first_one = NeuralVoice(folder, device="cpu")
        second_one = NeuralVoice(folder, device="cpu")
        assert first_one._load() is second_one._load()
        assert done_ones == ["cpu"]

    def test_another_language_opens_its_own(self, openings):
        """An English voice is not the French voice."""
        from greffier.adapters.voice_neural import NeuralVoice

        done_ones, folder = openings
        NeuralVoice(folder, language="fr", device="cpu")._load()
        NeuralVoice(folder, language="en", device="cpu")._load()
        assert len(done_ones) == 2

    def test_warming_opens_it_without_saying_anything(self, openings):
        from greffier.adapters.voice_neural import NeuralVoice

        done_ones, folder = openings
        NeuralVoice(folder, device="cpu").warm()
        assert done_ones == ["cpu"]

    def test_warming_never_raises(self, monkeypatch, openings):
        """Called from a thread while somebody speaks: a failure here costs nothing."""
        from greffier.adapters import voice_neural

        _, folder = openings

        def which_refuses(_self, _where):
            raise RuntimeError("modèle illisible")

        monkeypatch.setattr(voice_neural.NeuralVoice, "_open", which_refuses)
        voice_neural.NeuralVoice(folder, device="cpu").warm()


class TestSpeakingThroughTheSystemAndBeingQuiet:
    """The synthesiser stands in for a process that sleeps: what is covered is
    the voice's own handling of it, starting, refusing to cut itself, cutting."""

    def _voice(self, monkeypatch, seconds="2"):
        import sys

        monkeypatch.setattr(voice_system, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "/usr/bin/spd-say" if n == "spd-say" else None)
        voice = voice_system.SystemVoice(voice=None)
        monkeypatch.setattr(
            voice, "_command",
            lambda text: [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        )
        return voice

    def test_it_speaks_and_hands_back_at_once(self, monkeypatch):
        voice = self._voice(monkeypatch)
        try:
            assert voice.say("Bonjour à tous.") is True
            assert voice.is_speaking() is True
        finally:
            voice.go_quiet()
        assert voice.is_speaking() is False

    def test_it_refuses_to_cut_itself_for_a_second_remark(self, monkeypatch):
        voice = self._voice(monkeypatch)
        try:
            assert voice.say("Première phrase.") is True
            assert voice.say("Deuxième phrase.") is False
        finally:
            voice.go_quiet()

    def test_an_empty_remark_is_not_spoken(self, monkeypatch):
        assert self._voice(monkeypatch).say("   ") is False

    def test_waiting_ends_with_the_sentence(self, monkeypatch):
        voice = self._voice(monkeypatch, seconds="0.2")
        voice.say("Courte.")
        voice.wait_for_it(timeout=5)
        assert voice.is_speaking() is False

    def test_waiting_too_long_cuts_the_sentence(self, monkeypatch):
        voice = self._voice(monkeypatch, seconds="5")
        voice.say("Longue.")
        voice.wait_for_it(timeout=0.2)
        assert voice.is_speaking() is False

    def test_a_synthesiser_that_cannot_start_says_no(self, monkeypatch):
        voice = self._voice(monkeypatch)
        monkeypatch.setattr(voice, "_command", lambda text: ["/nowhere/to/be/found", text])
        assert voice.say("Bonjour.") is False


class TestARemarkSaidAsItComes:
    """The mouth: sentences in as the model finishes them, played in order.

    No model and no player here: the network is a double that returns a
    sample per sentence, the player a double that notes what it was given.
    """

    def _voice(self, tmp_path, monkeypatch):
        import numpy as np

        from greffier.adapters import voice_neural
        from greffier.adapters.voice_neural import NeuralVoice

        voice = NeuralVoice(tmp_path)
        played: list[str] = []
        monkeypatch.setattr(type(voice), "available", property(lambda _self: True))
        monkeypatch.setattr(voice, "_load", lambda: SimpleNamespace(
            generate=lambda text, sid, speed: SimpleNamespace(
                samples=np.zeros(160, dtype="float32"), sample_rate=16000)))
        monkeypatch.setattr(voice, "_play", lambda file: played.append(file.name) or True)
        monkeypatch.setattr(voice_neural, "WAIT_FOR_WORDS_S", 0.01)
        return voice, played

    def _until(self, condition, seconds=3.0):
        import time

        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert condition()

    def test_the_sentences_are_played_in_order_and_the_voice_is_busy_meanwhile(
        self, tmp_path, monkeypatch
    ):
        voice, played = self._voice(tmp_path, monkeypatch)
        mouth = voice.begin()
        assert mouth is not None
        mouth.add("Oui, je vous entends.")
        self._until(lambda: len(played) == 1)
        # Between two sentences, the model still writing: busy all the same.
        assert voice.is_speaking()
        mouth.add("La recette est jeudi. Voilà.")
        mouth.close()
        self._until(lambda: not voice.is_speaking())
        assert played == ["0.wav", "1.wav", "2.wav"]

    def test_a_second_remark_is_refused_while_the_first_is_under_way(
        self, tmp_path, monkeypatch
    ):
        voice, _ = self._voice(tmp_path, monkeypatch)
        mouth = voice.begin()
        assert voice.begin() is None
        assert not voice.say("Une autre.")
        mouth.close()
        self._until(lambda: not voice.is_speaking())
        assert voice.begin() is not None

    def test_say_goes_through_the_same_mouth(self, tmp_path, monkeypatch):
        voice, played = self._voice(tmp_path, monkeypatch)
        assert voice.say("Une phrase. Une autre.")
        self._until(lambda: not voice.is_speaking())
        assert played == ["0.wav", "1.wav"]

    def test_going_quiet_ends_a_remark_still_waiting_for_words(self, tmp_path, monkeypatch):
        voice, _ = self._voice(tmp_path, monkeypatch)
        mouth = voice.begin()
        assert mouth is not None
        voice.go_quiet()
        self._until(lambda: not voice.is_speaking())

    def test_a_remark_nobody_finishes_does_not_gag_the_voice_for_ever(
        self, tmp_path, monkeypatch
    ):
        from greffier.adapters import voice_neural

        monkeypatch.setattr(voice_neural, "PATIENCE_S", 0.05)
        voice, _ = self._voice(tmp_path, monkeypatch)
        assert voice.begin() is not None
        self._until(lambda: not voice.is_speaking())

    def test_the_system_voice_says_the_whole_remark_at_the_end(self, monkeypatch):
        said: list[str] = []
        voice = voice_system.SystemVoice(voice="Thomas")
        monkeypatch.setattr(type(voice), "available", property(lambda _self: True))
        monkeypatch.setattr(voice, "say", lambda text: said.append(text) or True)
        mouth = voice.begin()
        assert mouth is not None
        mouth.add("Une phrase.")
        assert said == []
        mouth.add("Une autre.")
        mouth.close()
        assert said == ["Une phrase. Une autre."]
