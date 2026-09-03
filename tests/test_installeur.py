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
        du poste (XFENCE), qui redemandaient une autorisation à chaque accès."""
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
                       "Library/Logs/Greffier.log", "local.xfence.rc", "opus"):
            assert indice in texte, indice

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
