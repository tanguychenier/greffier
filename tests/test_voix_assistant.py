"""La voix de l'assistant, sur les trois systèmes, sans en avoir trois.

Personne n'a un Mac, un poste Linux et un poste Windows sous la main. On force
donc le système détecté et on vérifie la commande construite : c'est là que se
jouent les fautes qui ne se voient qu'une fois sur place.
"""

from types import SimpleNamespace

from greffier.adapters import voice_neural, voice_system
from greffier.adapters.voice_neural import clean, sentences


class TestDecoupageDuPropos:
    def test_on_parle_des_la_premiere_phrase(self):
        """Générer tout le propos avant d'ouvrir la bouche fait attendre le tout.

        Générer la première pendant qu'on la prononce, c'est la latence de la
        première phrase seule.
        """
        assert sentences("Bonjour. Je suis Lucie. J'écoute.") == [
            "Bonjour.", "Je suis Lucie.", "J'écoute."]

    def test_une_periode_trop_longue_se_coupe_sur_ses_virgules(self):
        long = ", ".join(["un segment de texte assez long"] * 12) + "."
        chunks = sentences(long, maximum=100)
        assert len(chunks) > 1
        assert all(len(m) <= 120 for m in chunks)

    def test_les_tirets_deviennent_des_virgules(self):
        """Ils n'ont pas de phonème : le modèle les signale un par un et les saute."""
        assert clean("Bonjour — je suis là") == "Bonjour, je suis là"
        assert "—" not in clean("un — deux – trois-quatre")

    def test_un_propos_vide_ne_produit_rien(self):
        assert sentences("   ") == []
        assert sentences("") == []


class TestLecteurSelonLeSysteme:
    def test_macos_prend_afplay(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Darwin")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "/usr/bin/afplay" if n == "afplay" else None)
        assert voice_neural._player() == ["afplay"]

    def test_linux_prend_ce_qui_est_la(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "/usr/bin/aplay" if n == "aplay" else None)
        assert voice_neural._player() == ["/usr/bin/aplay"]

    def test_windows_retombe_sur_powershell(self, monkeypatch):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_neural.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        assert voice_neural._player()[0] == "powershell"

    def test_sans_lecteur_la_voix_se_declare_indisponible(self, monkeypatch, tmp_path):
        monkeypatch.setattr(voice_neural, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_neural.shutil, "which", lambda _n: None)
        assert voice_neural.NeuralVoice(tmp_path).available is False


class TestVoixDuSysteme:
    def test_windows_passe_par_la_synthese_integree(self, monkeypatch):
        monkeypatch.setattr(voice_system, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        command = voice_system.SystemVoice(voice=None)._command("bonjour")
        assert command[0] == "powershell"
        assert "System.Speech" in command[-1]
        assert "bonjour" in command[-1]

    def test_une_apostrophe_ne_casse_pas_la_commande_windows(self, monkeypatch):
        """Un propos français en contient à chaque phrase.

        Le texte entre dans un littéral PowerShell : seuls les guillemets
        simples s'y doublent, et rien n'y est interpolé.
        """
        monkeypatch.setattr(voice_system, "SYSTEM", "Windows")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        command = voice_system.SystemVoice(voice=None)._command("j'arrive")
        assert "j''arrive" in command[-1]

    def test_linux_prend_le_synthetiseur_present(self, monkeypatch):
        monkeypatch.setattr(voice_system, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_system.shutil, "which",
                            lambda n: "/usr/bin/spd-say" if n == "spd-say" else None)
        assert voice_system.SystemVoice(voice=None)._command("salut")[0] == "spd-say"

    def test_linux_sans_rien_ne_parle_pas(self, monkeypatch):
        monkeypatch.setattr(voice_system, "SYSTEM", "Linux")
        monkeypatch.setattr(voice_system.shutil, "which", lambda _n: None)
        assert voice_system.SystemVoice(voice=None)._command("salut") == []


class TestChoixDeLaVoix:
    def _voice(self, monkeypatch, listing):
        monkeypatch.setattr(voice_system, "SYSTEM", "Darwin")
        monkeypatch.setattr(voice_system.shutil, "which", lambda _n: "/usr/bin/say")
        monkeypatch.setattr(
            voice_system.subprocess, "run",
            lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=listing))

    def test_une_voix_amelioree_l_emporte(self, monkeypatch):
        self._voice(monkeypatch,
                   "Thomas               fr_FR    # Bonjour\n"
                   "Thomas (Premium)     fr_FR    # Bonjour\n")
        assert voice_system.best_voice() == "Thomas (Premium)"
        assert voice_system.better_voice_available()

    def test_a_defaut_une_compacte_acceptable(self, monkeypatch):
        """Les voix « eloquence » sont un synthétiseur des années 1980.

        Mesuré ailleurs : un modèle de transcription n'en tire rien du tout.
        En réunion, elles s'entendent immédiatement.
        """
        self._voice(monkeypatch,
                   "Jacques              fr_FR    # Bonjour\n"
                   "Thomas               fr_FR    # Bonjour\n")
        assert voice_system.best_voice() == "Thomas"
        assert not voice_system.better_voice_available()

    def test_la_france_avant_le_quebec(self, monkeypatch):
        self._voice(monkeypatch,
                   "Amélie (Premium)     fr_CA    # Bonjour\n"
                   "Thomas (Premium)     fr_FR    # Bonjour\n")
        assert voice_system.best_voice() == "Thomas (Premium)"

    def test_aucune_voix_francaise_laisse_choisir_le_systeme(self, monkeypatch):
        self._voice(monkeypatch, "Daniel               en_GB    # Hello\n")
        assert voice_system.best_voice() is None


class TestCouperLeSonDepuisUnAutreProcessus:
    """Le bouton « couper » est dans la fenêtre, la voix dans la veille.

    Le bouton écrivait un réglage que la veille ne relit qu'à la tranche
    suivante, soit jusqu'à quinze secondes plus tard. Mesuré en réunion : on
    appuie, elle continue de parler, et le bouton paraît cassé. Il l'était, du
    point de vue de qui appuie.
    """

    def test_le_baillon_porte_le_numero_du_lecteur(self, tmp_path):
        from greffier.adapters.voice_neural import NeuralVoice

        gag = tmp_path / "parole.pid"
        voice = NeuralVoice(tmp_path, gag=gag)
        voice._publish_the_gag(4242)
        assert gag.read_text() == "4242"

    def test_il_est_effacé_quand_le_son_s_arrête(self, tmp_path):
        """Un numéro qui traîne ferait tuer un processus qui n'est plus le nôtre.

        Sur un système qui recycle les numéros, ce serait n'importe lequel.
        """
        from greffier.adapters.voice_neural import NeuralVoice

        gag = tmp_path / "parole.pid"
        voice = NeuralVoice(tmp_path, gag=gag)
        voice._publish_the_gag(4242)
        voice._publish_the_gag(None)
        assert not gag.exists()

    def test_sans_baillon_rien_n_est_ecrit(self, tmp_path):
        """La ligne de commande n'a personne à qui parler."""
        from greffier.adapters.voice_neural import NeuralVoice

        NeuralVoice(tmp_path)._publish_the_gag(4242)
        assert list(tmp_path.iterdir()) == []

    def test_faire_taire_coupe_le_processus_designe(self, tmp_path):
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

    def test_faire_taire_sans_rien_a_couper_ne_leve_pas(self, tmp_path):
        """Le cas courant : personne ne parle."""
        from greffier.adapters.voice_neural import silence

        assert not silence(tmp_path / "absent.pid")

    def test_un_numero_mort_ne_leve_pas(self, tmp_path):
        from greffier.adapters.voice_neural import silence

        gag = tmp_path / "parole.pid"
        gag.write_text("999999")
        assert not silence(gag)

    def test_un_baillon_illisible_ne_leve_pas(self, tmp_path):
        from greffier.adapters.voice_neural import silence

        gag = tmp_path / "parole.pid"
        gag.write_text("ce n'est pas un numéro")
        assert not silence(gag)


class TestUneCoupureArreteToutLePropos:
    """Couper doit faire taire, pas sauter une phrase.

    Un propos est découpé en phrases jouées l'une après l'autre. Tuer le lecteur
    de la phrase en cours laissait la suivante repartir : elle s'arrêtait puis
    reprenait, ce qui est pire que de ne pas s'arrêter du tout.
    """

    def _voice(self, tmp_path, monkeypatch, retour):
        """Une voix dont le lecteur rend le code de retour voulu."""
        from greffier.adapters import voice_neural

        class Lecture:
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
                            lambda *_a, **_k: Lecture())
        return voice_neural.NeuralVoice(tmp_path, gag=tmp_path / "p.pid")

    def test_un_lecteur_tue_par_un_signal_arrete_la_suite(self, tmp_path, monkeypatch):
        """`afplay` tué par SIGTERM rend -15 : c'est le bouton, pas une fin."""
        voice = self._voice(tmp_path, monkeypatch, retour=-15)
        assert voice._play(tmp_path / "un.wav") is False
        assert voice._interrompu.is_set(), "la suite du propos n'a pas été annulée"

    def test_un_lecteur_qui_finit_normalement_laisse_la_suite(self, tmp_path,
                                                              monkeypatch):
        voice = self._voice(tmp_path, monkeypatch, retour=0)
        assert voice._play(tmp_path / "un.wav") is True
        assert not voice._interrompu.is_set()

    def test_le_baillon_est_efface_dans_les_deux_cas(self, tmp_path, monkeypatch):
        for retour in (-15, 0):
            voice = self._voice(tmp_path, monkeypatch, retour=retour)
            voice._play(tmp_path / "un.wav")
            assert not (tmp_path / "p.pid").exists()
