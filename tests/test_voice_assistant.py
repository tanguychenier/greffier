"""La voix de l'assistant, sur les trois systèmes, sans en avoir trois.

Personne n'a un Mac, un poste Linux et un poste Windows sous la main. On force
donc le système détecté et on vérifie la commande construite : c'est là que se
jouent les fautes qui ne se voient qu'une fois sur place.
"""

from types import SimpleNamespace

from greffier.adapters import voice_neural, voice_system
from greffier.adapters.voice_neural import clean, sentences


class TestCuttingTheRemarkIntoPieces:
    def test_it_starts_speaking_on_the_first_sentence(self):
        """Générer tout le propos avant d'ouvrir la bouche fait attendre le tout.

        Générer la première pendant qu'on la prononce, c'est la latence de la
        première phrase seule.
        """
        assert sentences("Bonjour. Je suis Lucie. J'écoute.") == [
            "Bonjour.", "Je suis Lucie.", "J'écoute."]

    def test_too_long_a_sentence_is_cut_on_its_commas(self):
        long = ", ".join(["un segment de texte assez long"] * 12) + "."
        chunks = sentences(long, maximum=100)
        assert len(chunks) > 1
        assert all(len(m) <= 120 for m in chunks)

    def test_the_dashes_become_commas(self):
        """Ils n'ont pas de phonème : le modèle les signale un par un et les saute."""
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
        assert voice_neural._player() == ["afplay"]

    def test_linux_takes_whatever_is_there(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "/usr/bin/aplay" if n == "aplay" else None)
        assert voice_neural._player() == ["/usr/bin/aplay"]

    def test_windows_falls_back_to_powershell(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        assert voice_neural._player()[0] == "powershell"

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
        """Un propos français en contient à chaque phrase.

        Le texte entre dans un littéral PowerShell : seuls les guillemets
        simples s'y doublent, et rien n'y est interpolé.
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
        """Les voix « eloquence » sont un synthétiseur des années 1980.

        Mesuré ailleurs : un modèle de transcription n'en tire rien du tout.
        En réunion, elles s'entendent immédiatement.
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
    """Le bouton « couper » est dans la fenêtre, la voix dans la veille.

    Le bouton écrivait un réglage que la veille ne relit qu'à la tranche
    suivante, soit jusqu'à quinze secondes plus tard. Mesuré en réunion : on
    appuie, elle continue de parler, et le bouton paraît cassé. Il l'était, du
    point de vue de qui appuie.
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
    """Couper doit faire taire, pas sauter une phrase.

    Un propos est découpé en phrases jouées l'une après l'autre. Tuer le lecteur
    de la phrase en cours laissait la suivante repartir : elle s'arrêtait puis
    reprenait, ce qui est pire que de ne pas s'arrêter du tout.
    """

    def _voice_of(self, tmp_path, monkeypatch, retour):
        """Une voix dont le lecteur rend le code de retour voulu."""
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

        monkeypatch.setattr(voice_neural, "_player", lambda: ["afplay"])
        monkeypatch.setattr(voice_neural.subprocess, "Popen",
                            lambda *_a, **_k: ReadBack())
        return voice_neural.NeuralVoice(tmp_path, gag=tmp_path / "p.pid")

    def test_a_player_killed_by_a_signal_stops_what_follows(self, tmp_path, monkeypatch):
        """`afplay` tué par SIGTERM rend -15 : c'est le bouton, pas une fin."""
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
