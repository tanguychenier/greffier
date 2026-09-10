"""Les décisions de l'installeur, vérifiées pour les trois systèmes.

Personne n'a un Mac, un poste Linux et un poste Windows sous la main. Ces tests
forcent le système détecté et vérifient ce que l'installeur en déduit : chemins,
gestionnaire de paquets, fichier de démarrage automatique. Ils tournent donc
partout et couvrent Windows depuis un Mac.

L'installeur est un script autonome — il doit fonctionner avant que le paquet ne
soit installé — d'où l'import par chemin plutôt que par nom de module.
"""

import importlib.util
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


def charger_installeur():
    specification = importlib.util.spec_from_file_location(
        "installeur", RACINE / "outils" / "installer.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def installeur():
    return charger_installeur()


@pytest.fixture
def sous(installeur, monkeypatch):
    """Fait croire à l'installeur qu'il tourne sur le système demandé."""

    def basculer(systeme, **variables):
        monkeypatch.setattr(installeur, "SYSTEME", systeme)
        for clef, valeur in variables.items():
            monkeypatch.setenv(clef, valeur)
        return installeur

    return basculer


class TestChemins:
    def test_linux_suit_les_conventions_xdg(self, sous, tmp_path, monkeypatch):
        module = sous("Linux", XDG_CONFIG_HOME=str(tmp_path / "config"))
        assert module.dossier_config() == tmp_path / "config" / "greffier"

    def test_macos_utilise_application_support(self, sous, monkeypatch, tmp_path):
        """Pas XDG : les dossiers cachés du compte sont surveillés par les gardes
        du poste, qui redemandaient une autorisation à chaque accès."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        module = sous("Darwin")
        attendu = tmp_path / "Library/Application Support/Greffier"
        assert module.dossier_config() == attendu
        assert module.dossier_donnees() == attendu

    def test_l_installeur_et_l_application_disent_la_meme_chose(self, sous, monkeypatch, tmp_path):
        """Une seule définition des emplacements : sinon l'installeur cherche
        les modèles là où l'application ne les met pas — et les retélécharge."""
        from greffier import emplacements

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        module = sous("Darwin")
        assert module.dossier_donnees() == emplacements.dossier_donnees("Darwin")

    def test_windows_utilise_appdata(self, sous, tmp_path):
        module = sous("Windows", APPDATA=str(tmp_path / "Roaming"),
                      LOCALAPPDATA=str(tmp_path / "Local"))
        assert module.dossier_config() == tmp_path / "Roaming" / "greffier"
        assert module.dossier_donnees() == tmp_path / "Local" / "greffier"


class TestGestionnaireDePaquets:
    def test_windows_prefere_winget_a_scoop(self, sous, monkeypatch):
        module = sous("Windows")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "C:\\\\winget.exe")
        outil, _ = module.gestionnaire()
        assert outil == "winget"

    def test_windows_sans_gestionnaire_ne_plante_pas(self, sous, monkeypatch):
        module = sous("Windows")
        monkeypatch.setattr(module.shutil, "which", lambda outil: None)
        assert module.gestionnaire() is None

    def test_linux_reconnait_apt(self, sous, monkeypatch):
        module = sous("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/apt-get"
                            if outil == "apt-get" else None)
        outil, commande = module.gestionnaire()
        assert outil == "apt-get" and "install" in commande

    def test_root_n_appelle_pas_sudo(self, sous, monkeypatch):
        """En conteneur et en intégration continue, sudo n'est pas installé."""
        module = sous("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/apt-get"
                            if outil == "apt-get" else None)
        monkeypatch.setattr(module.os, "geteuid", lambda: 0, raising=False)
        _, commande = module.gestionnaire()
        assert "sudo" not in commande

    def test_utilisateur_ordinaire_passe_par_sudo(self, sous, monkeypatch):
        module = sous("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/apt-get"
                            if outil == "apt-get" else None)
        monkeypatch.setattr(module.os, "geteuid", lambda: 501, raising=False)
        _, commande = module.gestionnaire()
        assert commande[0] == "sudo"

    def test_ffmpeg_est_connu_de_tous_les_gestionnaires(self, installeur):
        """C'est le seul outil vraiment indispensable : il doit s'installer partout."""
        attendus = {"brew", "apt-get", "dnf", "pacman", "zypper", "apk", "winget", "scoop"}
        assert attendus <= set(installeur.PAQUETS["ffmpeg"])


class TestIntegrationAuBureau:
    """Ce qui sera déposé pour lancer Greffier à l'ouverture de session."""

    def test_macos_produit_un_launch_agent(self, sous, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        module = sous("Darwin")
        fichier = module.integrer_au_bureau(None, "/Applications/Greffier.app")
        assert fichier.parent == tmp_path / "Library/LaunchAgents"
        contenu = fichier.read_text(encoding="utf-8")
        assert "com.reunions.greffier" in contenu and "RunAtLoad" in contenu

    def test_linux_produit_un_raccourci_desktop(self, sous, monkeypatch, tmp_path):
        module = sous("Linux", XDG_CONFIG_HOME=str(tmp_path / "config"))
        fichier = module.integrer_au_bureau(None, "/usr/local/bin/greffier")
        assert fichier == tmp_path / "config/autostart/greffier.desktop"
        contenu = fichier.read_text(encoding="utf-8")
        assert contenu.startswith("[Desktop Entry]")
        assert "Exec=/usr/local/bin/greffier" in contenu

    def test_windows_produit_un_script_de_demarrage(self, sous, tmp_path):
        module = sous("Windows", APPDATA=str(tmp_path / "Roaming"))
        fichier = module.integrer_au_bureau(None, r"C:\\Greffier\\greffier.exe")
        assert fichier.parent.name == "Startup"
        contenu = fichier.read_text(encoding="utf-8")
        # Un .cmd et non un .lnk : le raccourci Windows est un format binaire
        # qui exige PowerShell et COM, pour le même résultat.
        assert fichier.suffix == ".cmd" and "start" in contenu

    def test_un_systeme_inconnu_ne_plante_pas(self, sous):
        module = sous("Haiku")
        assert module.integrer_au_bureau(None, "/quelque/part") is None


class TestSkillDeDepannage:
    """Le skill qui apprend à Claude Code à réparer une installation.

    Greffier dépend d'une instance Claude Code authentifiée pour rédiger : c'est
    vers elle qu'on se tourne quand quelque chose casse, et sans ce document
    elle ignore l'essentiel — emplacements natifs, signature stable, modèle par
    défaut choisi à dessein.
    """

    def test_le_skill_est_livre_avec_le_depot(self, installeur):
        source = RACINE / "skills/greffier/SKILL.md"
        assert source.exists(), "le skill doit vivre dans le dépôt, pas seulement sur un poste"
        texte = source.read_text(encoding="utf-8")
        assert texte.startswith("---\nname: greffier\n"), "en-tête de skill attendu"
        assert "description:" in texte.split("---")[1]

    def test_le_skill_dit_ou_regarder(self, installeur):
        """Un skill qui n'indique ni les journaux ni le diagnostic ferait tâtonner."""
        texte = (RACINE / "skills/greffier/SKILL.md").read_text(encoding="utf-8")
        for indice in ("greffier diagnostic", "Application Support",
                       "Library/Logs/Greffier.log", "greffier rediger", "opus"):
            assert indice in texte, indice

    def test_tous_les_skills_du_depot_ont_un_en_tete(self):
        """Un skill sans en-tête n'est pas chargé, et rien ne le signale."""
        trouves = sorted((RACINE / "skills").glob("*/SKILL.md"))
        assert len(trouves) >= 2, "le dépôt porte le dépannage et l'assistance"
        for chemin in trouves:
            texte = chemin.read_text(encoding="utf-8")
            assert texte.startswith(f"---\nname: {chemin.parent.name}\n"), chemin
            assert "description:" in texte.split("---")[1], chemin

    def test_le_skill_d_assistance_dit_ce_qui_ne_se_fait_pas(self):
        """La proactivité sans garde-fou est une nuisance en réunion."""
        texte = (RACINE / "skills/assister-une-reunion/SKILL.md").read_text(
            encoding="utf-8")
        aplati = " ".join(texte.split())
        assert "Rien ne surgit" in aplati
        assert "jamais la phrase de la réunion" in aplati
        assert "Ne jamais effacer ce qu'un humain a posé" in aplati

    def test_il_est_pose_la_ou_claude_code_le_cherche(self, sous, monkeypatch, tmp_path):
        module = sous("Darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert module.dossier_skills() == tmp_path / ".claude/skills"

    def test_une_copie_et_non_un_lien(self, sous, monkeypatch, tmp_path):
        """Le dépôt peut être déplacé : un lien pointerait dans le vide."""
        module = sous("Darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/local/bin/claude")

        class Contexte:
            oui = True
            verifier_seulement = False
            a_faire: list[str] = []

            def demander(self, _question):
                return True

        module.etape_skill(Contexte())
        pose = tmp_path / ".claude/skills/greffier/SKILL.md"
        assert pose.is_file() and not pose.is_symlink()
        assert pose.read_text(encoding="utf-8") == (
            RACINE / "skills/greffier/SKILL.md").read_text(encoding="utf-8")

    def test_sans_claude_code_rien_n_est_pose(self, sous, monkeypatch, tmp_path):
        module = sous("Darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(module.shutil, "which", lambda outil: None)

        class Contexte:
            oui = True
            verifier_seulement = False
            a_faire: list[str] = []

            def demander(self, _question):
                return True

        module.etape_skill(Contexte())
        assert not (tmp_path / ".claude").exists()


class TestConsole:
    def test_les_symboles_ont_un_repli_ascii(self, installeur):
        """Une console Windows en cp1252 ne sait pas écrire « ✓ »."""
        assert set(installeur.SYMBOLES) == {"ok", "alerte", "erreur"}
        assert all(valeur for valeur in installeur.SYMBOLES.values())

    def test_le_repli_est_choisi_selon_l_encodage(self, installeur, monkeypatch):
        class ConsoleLimitee:
            encoding = "cp1252"

        monkeypatch.setattr(installeur.sys, "stdout", ConsoleLimitee())
        assert installeur._ecrivable("✓") is False
        assert installeur._ecrivable("ok") is True


class TestCaptureDuSonSousLinux:
    """Ce sur quoi l'installeur juge la capture du son des autres.

    « pactl » n'enregistre rien : il interroge le serveur de son, quand ffmpeg
    s'y branche directement par sa prise. Le juger absent annonçait une capture
    impossible sur une machine qui en était capable, et envoyait chercher un
    paquet inutile.
    """

    def test_la_prise_du_serveur_suffit(self, sous, monkeypatch, tmp_path):
        module = sous("Linux", XDG_RUNTIME_DIR=str(tmp_path))
        monkeypatch.delenv("PULSE_SERVER", raising=False)
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)
        (tmp_path / "pulse").mkdir()
        (tmp_path / "pulse" / "native").touch()

        assert module.serveur_de_son_present()

    def test_sans_serveur_il_n_y_a_rien_a_capter(self, sous, monkeypatch, tmp_path):
        module = sous("Linux", XDG_RUNTIME_DIR=str(tmp_path))
        monkeypatch.delenv("PULSE_SERVER", raising=False)

        assert not module.serveur_de_son_present()

    def test_un_serveur_declare_est_cru(self, sous, monkeypatch, tmp_path):
        """Un serveur distant ne pose aucune prise dans cette session."""
        module = sous("Linux", XDG_RUNTIME_DIR=str(tmp_path),
                      PULSE_SERVER="tcp:192.168.1.10:4713")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)

        assert module.serveur_de_son_present()


class TestAccelerationParLaCarte:
    """Une carte NVIDIA ne suffit pas à accélérer la transcription.

    CTranslate2 réclame cuBLAS et cuDNN, qu'aucune distribution ne livre avec
    le pilote. Sans elles la transcription tombe sur le processeur — treize
    fois le temps réel, mesuré, soit treize heures pour une réunion d'une
    heure. L'installeur doit donc les proposer, et seulement là où elles
    servent.
    """

    def test_une_carte_est_reconnue(self, sous, monkeypatch):
        module = sous("Linux")
        monkeypatch.setattr(module.shutil, "which",
                            lambda outil: "/usr/bin/nvidia-smi" if outil == "nvidia-smi" else None)

        assert module.carte_nvidia()

    def test_sans_carte_rien_n_est_propose(self, sous, monkeypatch):
        module = sous("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)

        assert not module.carte_nvidia()

    def test_macos_est_servi_par_metal(self, sous, monkeypatch):
        """Aucune carte NVIDIA n'y est utilisable, et la puce a déjà Metal."""
        module = sous("Darwin")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: "/usr/bin/nvidia-smi")

        assert not module.carte_nvidia()


class TestLaLangueDuPoste:
    """L'installeur gravait « fr » dans le gabarit, quel que soit le poste.

    La langue que le système annonce est un renseignement gratuit que rien ne
    lisait : un poste allemand ressortait réglé sur le français, et personne ne
    s'en apercevait avant la première transcription.
    """

    def test_la_langue_annoncee_est_retenue(self, sous, monkeypatch):
        module = sous("Linux", LANG="de_DE.UTF-8")
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)

        assert module.langue_du_poste() == "de"

    def test_une_langue_inconnue_retombe_sur_le_francais(self, sous, monkeypatch):
        module = sous("Linux", LANG="xx_XX.UTF-8")
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)

        assert module.langue_du_poste() == "fr"

    def test_sans_variable_le_francais(self, sous, monkeypatch):
        module = sous("Linux")
        for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
            monkeypatch.delenv(variable, raising=False)

        assert module.langue_du_poste() == "fr"

    def test_le_gabarit_ne_porte_plus_de_langue_en_dur(self, installeur):
        """Première couverture du gabarit : la ligne pouvait changer en silence."""
        assert 'langue = "fr"' not in installeur.GABARIT
        assert "langue = {langue!r}" in installeur.GABARIT

    def test_le_catalogue_des_langues_se_charge_sans_le_paquet(self, installeur):
        """L'installeur tourne avant que quoi que ce soit ne soit installé."""
        langues = installeur._charger_langues()

        assert langues is not None
        assert ("fr", "Français") in langues.LANGUES


class TestEnvironnementHerite:
    """Un « .venv » venu d'une autre machine ne doit pas passer pour valide.

    Le cas mesuré : une image Linux construite depuis un dépôt de travail
    macOS. Le dossier `.venv` était copié, ses liens ne menaient nulle part,
    et l'installeur — qui ne regardait que l'existence du dossier — sautait la
    création puis tombait sur « No such file or directory: .venv/bin/python ».
    L'installation s'arrêtait là, ce qui donne « rien ne marche sous Linux ».
    """

    def _preparer(self, installeur, tmp_path, monkeypatch, avec_uv):
        lancees = []
        monkeypatch.setattr(installeur, "DEPOT", tmp_path)
        monkeypatch.setattr(installeur, "SYSTEME", "Linux")
        monkeypatch.setattr(installeur.shutil, "which",
                            lambda nom: "/usr/bin/uv" if (nom == "uv" and avec_uv) else None)
        monkeypatch.setattr(installeur, "lancer",
                            lambda commande, **_: lancees.append(list(commande)))
        monkeypatch.setattr(installeur, "carte_nvidia", lambda: False)
        return lancees

    def test_un_venv_sans_interprete_est_refait(self, installeur, tmp_path, monkeypatch):
        lancees = self._preparer(installeur, tmp_path, monkeypatch, avec_uv=True)
        # Le dossier existe, l'interpréteur non : exactement l'état d'un venv
        # copié d'une machine à l'autre.
        (tmp_path / ".venv" / "bin").mkdir(parents=True)

        contexte = type("Ctx", (), {"verifier_seulement": False, "a_faire": [],
                                    "demander": lambda self, _q: False})()
        installeur.etape_environnement(contexte, "whisper.cpp")

        assert not (tmp_path / ".venv").exists() or lancees, "rien n'a été refait"
        assert any("venv" in " ".join(c) for c in lancees), lancees

    def test_un_venv_complet_n_est_pas_refait(self, installeur, tmp_path, monkeypatch):
        """Réinstaller à chaque lancement coûterait des minutes pour rien."""
        lancees = self._preparer(installeur, tmp_path, monkeypatch, avec_uv=True)
        interprete = tmp_path / ".venv" / "bin" / "python"
        interprete.parent.mkdir(parents=True)
        interprete.write_text("")

        contexte = type("Ctx", (), {"verifier_seulement": False, "a_faire": [],
                                    "demander": lambda self, _q: False})()
        installeur.etape_environnement(contexte, "whisper.cpp")

        assert not any(c[:2] == ["uv", "venv"] for c in lancees), lancees
        assert any("install" in " ".join(c) for c in lancees), lancees

    def test_sans_uv_ni_venv_l_installeur_s_arrete_en_le_disant(
        self, installeur, tmp_path, monkeypatch
    ):
        """Trois lignes plus bas, la trace Python n'aurait nommé aucun paquet."""
        self._preparer(installeur, tmp_path, monkeypatch, avec_uv=False)
        contexte = type("Ctx", (), {"verifier_seulement": False, "a_faire": [],
                                    "demander": lambda self, _q: False})()
        with pytest.raises(SystemExit):
            installeur.etape_environnement(contexte, "whisper.cpp")


class TestPresenceDeLaVoix:
    """Chercher « model.onnx » ne valait que pour Kokoro.

    Un VITS nomme ses poids d'après sa voix. L'installation annonçait donc la
    voix manquante alors qu'elle était en place, et proposait de retélécharger
    quatre-vingts mégaoctets à chaque passage.
    """

    def test_un_vits_est_reconnu(self, installeur, tmp_path):
        (tmp_path / "fr_FR-upmc-medium.onnx").write_text("")
        (tmp_path / "tokens.txt").write_text("")
        assert installeur.voix_presente(tmp_path)

    def test_un_kokoro_est_reconnu_aussi(self, installeur, tmp_path):
        (tmp_path / "model.onnx").write_text("")
        (tmp_path / "tokens.txt").write_text("")
        assert installeur.voix_presente(tmp_path)

    def test_un_reseau_sans_vocabulaire_ne_suffit_pas(self, installeur, tmp_path):
        """Le modèle ne se monte pas sans ses jetons : autant le dire avant."""
        (tmp_path / "fr_FR-upmc-medium.onnx").write_text("")
        assert not installeur.voix_presente(tmp_path)

    def test_un_dossier_vide_n_est_pas_une_voix(self, installeur, tmp_path):
        assert not installeur.voix_presente(tmp_path)
