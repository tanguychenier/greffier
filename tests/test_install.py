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


def load_the_installer():
    specification = importlib.util.spec_from_file_location(
        "installeur", RACINE / "tools" / "install.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def the_installer():
    return load_the_installer()


@pytest.fixture
def under(the_installer, monkeypatch):
    """Fait croire à l'installeur qu'il tourne sur le système demandé."""

    def basculer(system, **variables):
        monkeypatch.setattr(the_installer, "SYSTEM", system)
        for key, value in variables.items():
            monkeypatch.setenv(key, value)
        return the_installer

    return basculer


class TestWhereThingsLive:
    def test_linux_follows_the_xdg_conventions(self, under, tmp_path, monkeypatch):
        module = under("Linux", XDG_CONFIG_HOME=str(tmp_path / "config"))
        assert module.config_folder() == tmp_path / "config" / "greffier"

    def test_macos_uses_application_support(self, under, monkeypatch, tmp_path):
        """Pas XDG : les dossiers cachés du compte sont surveillés par les gardes
        du poste, qui redemandaient une autorisation à chaque accès."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        module = under("Darwin")
        expected = tmp_path / "Library/Application Support/Greffier"
        assert module.config_folder() == expected
        assert module.data_folder() == expected

    def test_the_installer_and_the_application_say_the_same_thing(
        self, under, monkeypatch, tmp_path
    ):
        """Une seule définition des emplacements : sinon l'installeur cherche
        les modèles là où l'application ne les met pas — et les retélécharge."""
        from greffier import locations

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        module = under("Darwin")
        assert module.data_folder() == locations.data_folder("Darwin")

    def test_windows_uses_appdata(self, under, tmp_path):
        module = under("Windows", APPDATA=str(tmp_path / "Roaming"),
                      LOCALAPPDATA=str(tmp_path / "Local"))
        assert module.config_folder() == tmp_path / "Roaming" / "greffier"
        assert module.data_folder() == tmp_path / "Local" / "greffier"


class TestThePackageManager:
    def test_windows_prefers_winget_to_scoop(self, under, monkeypatch):
        module = under("Windows")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "C:\\\\winget.exe")
        outil, _ = module.gestionnaire()
        assert outil == "winget"

    def test_windows_with_no_manager_does_not_crash(self, under, monkeypatch):
        module = under("Windows")
        monkeypatch.setattr(module.shutil, "which", lambda outil: None)
        assert module.gestionnaire() is None

    def test_linux_recognises_apt(self, under, monkeypatch):
        module = under("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/apt-get"
                            if outil == "apt-get" else None)
        outil, command = module.gestionnaire()
        assert outil == "apt-get" and "install" in command

    def test_root_does_not_call_sudo(self, under, monkeypatch):
        """En conteneur et en intégration continue, sudo n'est pas installé."""
        module = under("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/apt-get"
                            if outil == "apt-get" else None)
        monkeypatch.setattr(module.os, "geteuid", lambda: 0, raising=False)
        _, command = module.gestionnaire()
        assert "sudo" not in command

    def test_an_ordinary_user_goes_through_sudo(self, under, monkeypatch):
        module = under("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/apt-get"
                            if outil == "apt-get" else None)
        monkeypatch.setattr(module.os, "geteuid", lambda: 501, raising=False)
        _, command = module.gestionnaire()
        assert command[0] == "sudo"

    def test_ffmpeg_is_known_to_every_manager(self, the_installer):
        """C'est le seul outil vraiment indispensable : il doit s'installer partout."""
        attendus = {"brew", "apt-get", "dnf", "pacman", "zypper", "apk", "winget", "scoop"}
        assert attendus <= set(the_installer.PAQUETS["ffmpeg"])


class TestFittingIntoTheDesktop:
    """Ce qui sera déposé pour lancer Greffier à l'ouverture de session."""

    def test_macos_gets_a_launch_agent(self, under, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        module = under("Darwin")
        file = module.integrer_au_bureau(None, "/Applications/Greffier.app")
        assert file.parent == tmp_path / "Library/LaunchAgents"
        content = file.read_text(encoding="utf-8")
        assert "com.reunions.greffier" in content and "RunAtLoad" in content

    def test_linux_gets_a_desktop_entry(self, under, monkeypatch, tmp_path):
        module = under("Linux", XDG_CONFIG_HOME=str(tmp_path / "config"))
        file = module.integrer_au_bureau(None, "/usr/local/bin/greffier")
        assert file == tmp_path / "config/autostart/greffier.desktop"
        content = file.read_text(encoding="utf-8")
        assert content.startswith("[Desktop Entry]")
        assert "Exec=/usr/local/bin/greffier" in content

    def test_windows_gets_a_startup_script(self, under, tmp_path):
        module = under("Windows", APPDATA=str(tmp_path / "Roaming"))
        file = module.integrer_au_bureau(None, r"C:\\Greffier\\greffier.exe")
        assert file.parent.name == "Startup"
        content = file.read_text(encoding="utf-8")
        # Un .cmd et non un .lnk : le raccourci Windows est un format binaire
        # qui exige PowerShell et COM, pour le même résultat.
        assert file.suffix == ".cmd" and "start" in content

    def test_an_unknown_system_does_not_crash(self, under):
        module = under("Haiku")
        assert module.integrer_au_bureau(None, "/quelque/part") is None


class TestTheRepairSkill:
    """Le skill qui apprend à Claude Code à réparer une installation.

    Greffier dépend d'une instance Claude Code authentifiée pour rédiger : c'est
    vers elle qu'on se tourne quand quelque chose casse, et sans ce document
    elle ignore l'essentiel — emplacements natifs, signature stable, modèle par
    défaut choisi à dessein.
    """

    def test_the_skill_ships_with_the_repository(self, the_installer):
        source = RACINE / "skills/greffier/SKILL.md"
        assert source.exists(), "le skill doit vivre dans le dépôt, pas seulement sur un poste"
        text = source.read_text(encoding="utf-8")
        assert text.startswith("---\nname: greffier\n"), "en-tête de skill attendu"
        assert "description:" in text.split("---")[1]

    def test_the_skill_says_where_to_look(self, the_installer):
        """Un skill qui n'indique ni les journaux ni le diagnostic ferait tâtonner."""
        text = (RACINE / "skills/greffier/SKILL.md").read_text(encoding="utf-8")
        for indice in ("greffier diagnostic", "Application Support",
                       "Library/Logs/Greffier.log", "greffier rediger", "opus"):
            assert indice in text, indice

    def test_every_skill_in_the_repository_has_a_header(self):
        """Un skill sans en-tête n'est pas chargé, et rien ne le signale."""
        found = sorted((RACINE / "skills").glob("*/SKILL.md"))
        assert len(found) >= 2, "le dépôt porte le dépannage et l'assistance"
        for path in found:
            text = path.read_text(encoding="utf-8")
            assert text.startswith(f"---\nname: {path.parent.name}\n"), path
            assert "description:" in text.split("---")[1], path

    def test_the_meeting_skill_says_what_must_not_be_done(self):
        """La proactivité sans garde-fou est une nuisance en réunion."""
        text = (RACINE / "skills/assister-une-reunion/SKILL.md").read_text(
            encoding="utf-8")
        aplati = " ".join(text.split())
        assert "Rien ne surgit" in aplati
        assert "jamais la phrase de la réunion" in aplati
        assert "Ne jamais effacer ce qu'un humain a posé" in aplati

    def test_it_is_laid_where_the_assistant_looks_for_it(self, under, monkeypatch, tmp_path):
        module = under("Darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert module.dossier_skills() == tmp_path / ".claude/skills"

    def test_a_copy_and_not_a_link(self, under, monkeypatch, tmp_path):
        """Le dépôt peut être déplacé : un lien pointerait dans le vide."""
        module = under("Darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/local/bin/claude")

        class Context:
            yes = True
            check_only = False
            to_do: list[str] = []

            def ask(self, _question):
                return True

        module.etape_skill(Context())
        pose = tmp_path / ".claude/skills/greffier/SKILL.md"
        assert pose.is_file() and not pose.is_symlink()
        assert pose.read_text(encoding="utf-8") == (
            RACINE / "skills/greffier/SKILL.md").read_text(encoding="utf-8")

    def test_with_no_coding_assistant_nothing_is_laid_down(self, under, monkeypatch, tmp_path):
        module = under("Darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(module.shutil, "which", lambda outil: None)

        class Context:
            yes = True
            check_only = False
            to_do: list[str] = []

            def ask(self, _question):
                return True

        module.etape_skill(Context())
        assert not (tmp_path / ".claude").exists()


class TestWhatTheConsoleCanShow:
    def test_the_symbols_have_an_ascii_fallback(self, the_installer):
        """Une console Windows en cp1252 ne sait pas écrire « ✓ »."""
        assert set(the_installer.SYMBOLES) == {"ok", "alerte", "erreur"}
        assert all(value for value in the_installer.SYMBOLES.values())

    def test_the_fallback_is_chosen_from_the_encoding(self, the_installer, monkeypatch):
        class NarrowConsole:
            encoding = "cp1252"

        monkeypatch.setattr(the_installer.sys, "stdout", NarrowConsole())
        assert the_installer._ecrivable("✓") is False
        assert the_installer._ecrivable("ok") is True


class TestCapturingSoundOnLinux:
    """Ce sur quoi l'installeur juge la capture du son des autres.

    « pactl » n'enregistre rien : il interroge le serveur de son, quand ffmpeg
    s'y branche directement par sa prise. Le juger absent annonçait une capture
    impossible sur une machine qui en était capable, et envoyait chercher un
    paquet inutile.
    """

    def test_the_server_socket_is_enough(self, under, monkeypatch, tmp_path):
        module = under("Linux", XDG_RUNTIME_DIR=str(tmp_path))
        monkeypatch.delenv("PULSE_SERVER", raising=False)
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)
        (tmp_path / "pulse").mkdir()
        (tmp_path / "pulse" / "native").touch()

        assert module.sound_server_present()

    def test_with_no_server_there_is_nothing_to_capture(self, under, monkeypatch, tmp_path):
        module = under("Linux", XDG_RUNTIME_DIR=str(tmp_path))
        monkeypatch.delenv("PULSE_SERVER", raising=False)

        assert not module.sound_server_present()

    def test_a_declared_server_is_believed(self, under, monkeypatch, tmp_path):
        """Un serveur distant ne pose aucune prise dans cette session."""
        module = under("Linux", XDG_RUNTIME_DIR=str(tmp_path),
                      PULSE_SERVER="tcp:192.168.1.10:4713")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)

        assert module.sound_server_present()


class TestAccelerationByTheCard:
    """Une carte NVIDIA ne suffit pas à accélérer la transcription.

    CTranslate2 réclame cuBLAS et cuDNN, qu'aucune distribution ne livre avec
    le pilote. Sans elles la transcription tombe sur le processeur — treize
    fois le temps réel, mesuré, soit treize heures pour une réunion d'une
    heure. L'installeur doit donc les proposer, et seulement là où elles
    servent.
    """

    def test_a_card_is_recognised(self, under, monkeypatch):
        module = under("Linux")
        monkeypatch.setattr(module.shutil, "which",
                            lambda outil: "/usr/bin/nvidia-smi" if outil == "nvidia-smi" else None)

        assert module.carte_nvidia()

    def test_with_no_card_nothing_is_offered(self, under, monkeypatch):
        module = under("Linux")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)

        assert not module.carte_nvidia()

    def test_macos_is_served_by_metal(self, under, monkeypatch):
        """Aucune carte NVIDIA n'y est utilisable, et la puce a déjà Metal."""
        module = under("Darwin")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: "/usr/bin/nvidia-smi")

        assert not module.carte_nvidia()


class TestTheLanguageOfTheMachine:
    """L'installeur gravait « fr » dans le gabarit, quel que soit le poste.

    La langue que le système annonce est un renseignement gratuit que rien ne
    lisait : un poste allemand ressortait réglé sur le français, et personne ne
    s'en apercevait avant la première transcription.
    """

    def test_the_announced_language_is_kept(self, under, monkeypatch):
        module = under("Linux", LANG="de_DE.UTF-8")
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)

        assert module.system_language() == "de"

    def test_an_unknown_language_falls_back_to_french(self, under, monkeypatch):
        module = under("Linux", LANG="xx_XX.UTF-8")
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)

        assert module.system_language() == "fr"

    def test_with_no_variable_french(self, under, monkeypatch):
        module = under("Linux")
        for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
            monkeypatch.delenv(variable, raising=False)

        assert module.system_language() == "fr"

    def test_the_template_no_longer_hard_codes_a_language(self, the_installer):
        """Première couverture du gabarit : la ligne pouvait changer en silence."""
        assert 'langue = "fr"' not in the_installer.GABARIT
        assert "langue = {langue!r}" in the_installer.GABARIT

    def test_the_language_catalogue_loads_without_the_package(self, the_installer):
        """L'installeur tourne avant que quoi que ce soit ne soit installé."""
        languages = the_installer._charger_langues()

        assert languages is not None
        assert ("fr", "Français") in languages.LANGUAGES


class TestAnEnvironmentInheritedFromBefore:
    """Un « .venv » venu d'une autre machine ne doit pas passer pour valide.

    Le cas mesuré : une image Linux construite depuis un dépôt de travail
    macOS. Le dossier `.venv` était copié, ses liens ne menaient nulle part,
    et l'installeur — qui ne regardait que l'existence du dossier — sautait la
    création puis tombait sur « No such file or directory: .venv/bin/python ».
    L'installation s'arrêtait là, ce qui donne « rien ne marche sous Linux ».
    """

    def _prepare(self, the_installer, tmp_path, monkeypatch, avec_uv):
        lancees = []
        monkeypatch.setattr(the_installer, "ROOT", tmp_path)
        monkeypatch.setattr(the_installer, "SYSTEM", "Linux")
        monkeypatch.setattr(the_installer.shutil, "which",
                            lambda name: "/usr/bin/uv" if (name == "uv" and avec_uv) else None)
        monkeypatch.setattr(the_installer, "run_job",
                            lambda command, **_: lancees.append(list(command)))
        monkeypatch.setattr(the_installer, "carte_nvidia", lambda: False)
        return lancees

    def test_a_venv_with_no_interpreter_is_remade(self, the_installer, tmp_path, monkeypatch):
        lancees = self._prepare(the_installer, tmp_path, monkeypatch, avec_uv=True)
        # Le dossier existe, l'interpréteur non : exactement l'état d'un venv
        # copié d'une machine à l'autre.
        (tmp_path / ".venv" / "bin").mkdir(parents=True)

        context = type("Ctx", (), {"check_only": False, "to_do": [],
                                    "ask": lambda self, _q: False})()
        the_installer.etape_environnement(context, "whisper.cpp")

        assert not (tmp_path / ".venv").exists() or lancees, "rien n'a été refait"
        assert any("venv" in " ".join(c) for c in lancees), lancees

    def test_a_complete_venv_is_not_remade(self, the_installer, tmp_path, monkeypatch):
        """Réinstaller à chaque lancement coûterait des minutes pour rien."""
        lancees = self._prepare(the_installer, tmp_path, monkeypatch, avec_uv=True)
        interprete = tmp_path / ".venv" / "bin" / "python"
        interprete.parent.mkdir(parents=True)
        interprete.write_text("")

        context = type("Ctx", (), {"check_only": False, "to_do": [],
                                    "ask": lambda self, _q: False})()
        the_installer.etape_environnement(context, "whisper.cpp")

        assert not any(c[:2] == ["uv", "venv"] for c in lancees), lancees
        assert any("install" in " ".join(c) for c in lancees), lancees

    def test_with_neither_uv_nor_venv_the_installer_stops_and_says_so(
        self, the_installer, tmp_path, monkeypatch
    ):
        """Trois lignes plus bas, la trace Python n'aurait nommé aucun paquet."""
        self._prepare(the_installer, tmp_path, monkeypatch, avec_uv=False)
        context = type("Ctx", (), {"check_only": False, "to_do": [],
                                    "ask": lambda self, _q: False})()
        with pytest.raises(SystemExit):
            the_installer.etape_environnement(context, "whisper.cpp")


class TestWhetherTheVoiceIsThere:
    """Chercher « model.onnx » ne valait que pour Kokoro.

    Un VITS nomme ses poids d'après sa voix. L'installation annonçait donc la
    voix manquante alors qu'elle était en place, et proposait de retélécharger
    quatre-vingts mégaoctets à chaque passage.
    """

    def test_a_vits_model_is_recognised(self, the_installer, tmp_path):
        (tmp_path / "fr_FR-upmc-medium.onnx").write_text("")
        (tmp_path / "tokens.txt").write_text("")
        assert the_installer.voix_presente(tmp_path)

    def test_a_kokoro_model_is_recognised_too(self, the_installer, tmp_path):
        (tmp_path / "model.onnx").write_text("")
        (tmp_path / "tokens.txt").write_text("")
        assert the_installer.voix_presente(tmp_path)

    def test_a_network_without_its_vocabulary_is_not_enough(self, the_installer, tmp_path):
        """Le modèle ne se monte pas sans ses jetons : autant le dire avant."""
        (tmp_path / "fr_FR-upmc-medium.onnx").write_text("")
        assert not the_installer.voix_presente(tmp_path)

    def test_an_empty_folder_is_not_a_voice(self, the_installer, tmp_path):
        assert not the_installer.voix_presente(tmp_path)
