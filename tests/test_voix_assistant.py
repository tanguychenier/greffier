"""La voix de l'assistant, sur les trois systèmes, sans en avoir trois.

Personne n'a un Mac, un poste Linux et un poste Windows sous la main. On force
donc le système détecté et on vérifie la commande construite : c'est là que se
jouent les fautes qui ne se voient qu'une fois sur place.
"""

from types import SimpleNamespace

from greffier.adaptateurs import voix_neuronale, voix_systeme
from greffier.adaptateurs.voix_neuronale import nettoyer, phrases


class TestDecoupageDuPropos:
    def test_on_parle_des_la_premiere_phrase(self):
        """Générer tout le propos avant d'ouvrir la bouche fait attendre le tout.

        Générer la première pendant qu'on la prononce, c'est la latence de la
        première phrase seule.
        """
        assert phrases("Bonjour. Je suis Lucie. J'écoute.") == [
            "Bonjour.", "Je suis Lucie.", "J'écoute."]

    def test_une_periode_trop_longue_se_coupe_sur_ses_virgules(self):
        long = ", ".join(["un segment de texte assez long"] * 12) + "."
        morceaux = phrases(long, maximum=100)
        assert len(morceaux) > 1
        assert all(len(m) <= 120 for m in morceaux)

    def test_les_tirets_deviennent_des_virgules(self):
        """Ils n'ont pas de phonème : le modèle les signale un par un et les saute."""
        assert nettoyer("Bonjour — je suis là") == "Bonjour, je suis là"
        assert "—" not in nettoyer("un — deux – trois-quatre")

    def test_un_propos_vide_ne_produit_rien(self):
        assert phrases("   ") == []
        assert phrases("") == []


class TestLecteurSelonLeSysteme:
    def test_macos_prend_afplay(self, monkeypatch):
        monkeypatch.setattr(voix_neuronale, "SYSTEME", "Darwin")
        monkeypatch.setattr(voix_neuronale.shutil, "which",
                            lambda n: "/usr/bin/afplay" if n == "afplay" else None)
        assert voix_neuronale._lecteur() == ["afplay"]

    def test_linux_prend_ce_qui_est_la(self, monkeypatch):
        monkeypatch.setattr(voix_neuronale, "SYSTEME", "Linux")
        monkeypatch.setattr(voix_neuronale.shutil, "which",
                            lambda n: "/usr/bin/aplay" if n == "aplay" else None)
        assert voix_neuronale._lecteur() == ["/usr/bin/aplay"]

    def test_windows_retombe_sur_powershell(self, monkeypatch):
        monkeypatch.setattr(voix_neuronale, "SYSTEME", "Windows")
        monkeypatch.setattr(voix_neuronale.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        assert voix_neuronale._lecteur()[0] == "powershell"

    def test_sans_lecteur_la_voix_se_declare_indisponible(self, monkeypatch, tmp_path):
        monkeypatch.setattr(voix_neuronale, "SYSTEME", "Linux")
        monkeypatch.setattr(voix_neuronale.shutil, "which", lambda _n: None)
        assert voix_neuronale.VoixNeuronale(tmp_path).disponible is False


class TestVoixDuSysteme:
    def test_windows_passe_par_la_synthese_integree(self, monkeypatch):
        monkeypatch.setattr(voix_systeme, "SYSTEME", "Windows")
        monkeypatch.setattr(voix_systeme.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        commande = voix_systeme.VoixSysteme(voix=None)._commande("bonjour")
        assert commande[0] == "powershell"
        assert "System.Speech" in commande[-1]
        assert "bonjour" in commande[-1]

    def test_une_apostrophe_ne_casse_pas_la_commande_windows(self, monkeypatch):
        """Un propos français en contient à chaque phrase.

        Le texte entre dans un littéral PowerShell : seuls les guillemets
        simples s'y doublent, et rien n'y est interpolé.
        """
        monkeypatch.setattr(voix_systeme, "SYSTEME", "Windows")
        monkeypatch.setattr(voix_systeme.shutil, "which",
                            lambda n: "powershell.exe" if n == "powershell" else None)
        commande = voix_systeme.VoixSysteme(voix=None)._commande("j'arrive")
        assert "j''arrive" in commande[-1]

    def test_linux_prend_le_synthetiseur_present(self, monkeypatch):
        monkeypatch.setattr(voix_systeme, "SYSTEME", "Linux")
        monkeypatch.setattr(voix_systeme.shutil, "which",
                            lambda n: "/usr/bin/spd-say" if n == "spd-say" else None)
        assert voix_systeme.VoixSysteme(voix=None)._commande("salut")[0] == "spd-say"

    def test_linux_sans_rien_ne_parle_pas(self, monkeypatch):
        monkeypatch.setattr(voix_systeme, "SYSTEME", "Linux")
        monkeypatch.setattr(voix_systeme.shutil, "which", lambda _n: None)
        assert voix_systeme.VoixSysteme(voix=None)._commande("salut") == []


class TestChoixDeLaVoix:
    def _voix(self, monkeypatch, liste):
        monkeypatch.setattr(voix_systeme, "SYSTEME", "Darwin")
        monkeypatch.setattr(voix_systeme.shutil, "which", lambda _n: "/usr/bin/say")
        monkeypatch.setattr(
            voix_systeme.subprocess, "run",
            lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=liste))

    def test_une_voix_amelioree_l_emporte(self, monkeypatch):
        self._voix(monkeypatch,
                   "Thomas               fr_FR    # Bonjour\n"
                   "Thomas (Premium)     fr_FR    # Bonjour\n")
        assert voix_systeme.meilleure_voix() == "Thomas (Premium)"
        assert voix_systeme.voix_amelioree_disponible()

    def test_a_defaut_une_compacte_acceptable(self, monkeypatch):
        """Les voix « eloquence » sont un synthétiseur des années 1980.

        Mesuré ailleurs : un modèle de transcription n'en tire rien du tout.
        En réunion, elles s'entendent immédiatement.
        """
        self._voix(monkeypatch,
                   "Jacques              fr_FR    # Bonjour\n"
                   "Thomas               fr_FR    # Bonjour\n")
        assert voix_systeme.meilleure_voix() == "Thomas"
        assert not voix_systeme.voix_amelioree_disponible()

    def test_la_france_avant_le_quebec(self, monkeypatch):
        self._voix(monkeypatch,
                   "Amélie (Premium)     fr_CA    # Bonjour\n"
                   "Thomas (Premium)     fr_FR    # Bonjour\n")
        assert voix_systeme.meilleure_voix() == "Thomas (Premium)"

    def test_aucune_voix_francaise_laisse_choisir_le_systeme(self, monkeypatch):
        self._voix(monkeypatch, "Daniel               en_GB    # Hello\n")
        assert voix_systeme.meilleure_voix() is None


class TestCouperLeSonDepuisUnAutreProcessus:
    """Le bouton « couper » est dans la fenêtre, la voix dans la veille.

    Le bouton écrivait un réglage que la veille ne relit qu'à la tranche
    suivante, soit jusqu'à quinze secondes plus tard. Mesuré en réunion : on
    appuie, elle continue de parler, et le bouton paraît cassé. Il l'était, du
    point de vue de qui appuie.
    """

    def test_le_baillon_porte_le_numero_du_lecteur(self, tmp_path):
        from greffier.adaptateurs.voix_neuronale import VoixNeuronale

        baillon = tmp_path / "parole.pid"
        voix = VoixNeuronale(tmp_path, baillon=baillon)
        voix._publier_le_baillon(4242)
        assert baillon.read_text() == "4242"

    def test_il_est_effacé_quand_le_son_s_arrête(self, tmp_path):
        """Un numéro qui traîne ferait tuer un processus qui n'est plus le nôtre.

        Sur un système qui recycle les numéros, ce serait n'importe lequel.
        """
        from greffier.adaptateurs.voix_neuronale import VoixNeuronale

        baillon = tmp_path / "parole.pid"
        voix = VoixNeuronale(tmp_path, baillon=baillon)
        voix._publier_le_baillon(4242)
        voix._publier_le_baillon(None)
        assert not baillon.exists()

    def test_sans_baillon_rien_n_est_ecrit(self, tmp_path):
        """La ligne de commande n'a personne à qui parler."""
        from greffier.adaptateurs.voix_neuronale import VoixNeuronale

        VoixNeuronale(tmp_path)._publier_le_baillon(4242)
        assert list(tmp_path.iterdir()) == []

    def test_faire_taire_coupe_le_processus_designe(self, tmp_path):
        import subprocess
        import time

        from greffier.adaptateurs.voix_neuronale import faire_taire

        dormeur = subprocess.Popen(["sleep", "30"])
        baillon = tmp_path / "parole.pid"
        baillon.write_text(str(dormeur.pid))
        assert faire_taire(baillon)
        for _ in range(20):
            if dormeur.poll() is not None:
                break
            time.sleep(0.1)
        assert dormeur.poll() is not None, "le processus n'a pas été coupé"
        assert not baillon.exists()

    def test_faire_taire_sans_rien_a_couper_ne_leve_pas(self, tmp_path):
        """Le cas courant : personne ne parle."""
        from greffier.adaptateurs.voix_neuronale import faire_taire

        assert not faire_taire(tmp_path / "absent.pid")

    def test_un_numero_mort_ne_leve_pas(self, tmp_path):
        from greffier.adaptateurs.voix_neuronale import faire_taire

        baillon = tmp_path / "parole.pid"
        baillon.write_text("999999")
        assert not faire_taire(baillon)

    def test_un_baillon_illisible_ne_leve_pas(self, tmp_path):
        from greffier.adaptateurs.voix_neuronale import faire_taire

        baillon = tmp_path / "parole.pid"
        baillon.write_text("ce n'est pas un numéro")
        assert not faire_taire(baillon)
