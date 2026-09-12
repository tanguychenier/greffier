"""What the installer decides, checked for all three systems.

Nobody has a Mac, a Linux machine and a Windows machine to hand. These tests
force the detected system and check what the installer deduces from it: paths,
package manager, autostart file. They therefore run everywhere and cover
Windows from a Mac.

The installer is a standalone script, since it has to work before the package
is installed, hence the import by path rather than by module name.
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
    """Makes the installer believe it is running on the system asked for."""

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
        """Not XDG: the hidden folders of an account are watched by the machine's
        guards, which asked for permission again on every access.
        """
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
        """One definition of the locations: otherwise the installer looks for the models
        where the application does not put them, and downloads them again.
        """
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
        """In a container and in continuous integration, sudo is not installed."""
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
    """What gets laid down to start Greffier when the session opens."""

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
        # A .cmd and not a .lnk: a Windows shortcut is a binary format that
        # demands PowerShell and COM, for the same outcome.
        assert file.suffix == ".cmd" and "start" in content

    def test_an_unknown_system_does_not_crash(self, under):
        module = under("Haiku")
        assert module.integrer_au_bureau(None, "/quelque/part") is None


class TestTheRepairSkill:
    """The skill that teaches a coding assistant to repair an installation.

    Greffier depends on an authenticated assistant to write the minutes: it is
    what one turns to when something breaks, and without this document it misses
    the essentials — the native locations, the stable signature, the default model
    chosen on purpose.
    """

    def test_the_skill_ships_with_the_repository(self, the_installer):
        source = RACINE / "skills/greffier/SKILL.md"
        assert source.exists(), "le skill doit vivre dans le dépôt, pas seulement sur un poste"
        text = source.read_text(encoding="utf-8")
        assert text.startswith("---\nname: greffier\n"), "en-tête de skill attendu"
        assert "description:" in text.split("---")[1]

    def test_the_skill_says_where_to_look(self, the_installer):
        """A skill that names neither the logs nor the diagnostic leaves it groping."""
        text = (RACINE / "skills/greffier/SKILL.md").read_text(encoding="utf-8")
        for indice in ("greffier diagnostic", "Application Support",
                       "Library/Logs/Greffier.log", "greffier rediger", "opus"):
            assert indice in text, indice

    def test_every_skill_in_the_repository_has_a_header(self):
        """A skill with no header is not loaded, and nothing says so."""
        found = sorted((RACINE / "skills").glob("*/SKILL.md"))
        assert len(found) >= 2, "le dépôt porte le dépannage et l'assistance"
        for path in found:
            text = path.read_text(encoding="utf-8")
            assert text.startswith(f"---\nname: {path.parent.name}\n"), path
            assert "description:" in text.split("---")[1], path

    def test_the_meeting_skill_says_what_must_not_be_done(self):
        """Being proactive with no guard rail is a nuisance in a meeting."""
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
        """The repository may be moved: a link would point into the void."""
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

    def test_a_dead_link_where_the_skills_go_does_not_stop_the_install(
            self, under, monkeypatch, tmp_path):
        """`~/.claude/skills` pointing into a repository since moved.

        The name is taken, so mkdir refuses; it is taken by nothing, so there
        is nothing to protect. The installer used to stop on a stack trace
        here, after the models and the dependencies were already in place.
        """
        module = under("Linux")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(module.shutil, "which", lambda outil: "/usr/bin/claude")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude/skills").symlink_to(tmp_path / "gone/skills")

        class Context:
            yes = True
            check_only = False
            to_do: list[str] = []

            def ask(self, _question):
                return True

        module.etape_skill(Context())
        pose = tmp_path / ".claude/skills/greffier/SKILL.md"
        assert pose.is_file(), "the skill goes down once the dead link is out of the way"

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


class TestAWindowThatDoesNotLookLike1989:
    """« Les textes sont bizarres, comme pas net » -- reported on sight.

    The interpreter uv installs carries its own Tk, built without Xft: measured
    on the machine that reported it, `tk::pkgconfig get fontsystem` answers
    `x11` and offers 48 bitmap families, where the distribution's Tk answers
    `xft` and offers 266.
    """

    @staticmethod
    def _answering(module, monkeypatch, answer, code=0):
        class Lu:
            returncode = code
            stdout = answer
            stderr = ""

        monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: Lu())

    def test_xft_is_smoothing(self, under, monkeypatch):
        module = under("Linux", DISPLAY=":0")
        self._answering(module, monkeypatch, "xft\n")
        assert module.antialiases("/usr/bin/python3.13") is True

    def test_x11_is_not(self, under, monkeypatch):
        module = under("Linux", DISPLAY=":0")
        self._answering(module, monkeypatch, "x11\n")
        assert module.antialiases("/usr/bin/python3.13") is False

    def test_an_interpreter_that_refuses_answers_nothing(self, under, monkeypatch):
        module = under("Linux", DISPLAY=":0")
        self._answering(module, monkeypatch, "", code=1)
        assert module.antialiases("/usr/bin/python3.13") is None

    def test_over_ssh_the_question_cannot_be_asked(self, under, monkeypatch):
        """No display, no Tk, and no reason to fail the installation for it."""
        module = under("Linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        assert module.antialiases("/usr/bin/python3.13") is None

    def test_the_system_interpreter_is_preferred_when_it_smooths(
            self, under, monkeypatch):
        module = under("Linux", DISPLAY=":0")
        monkeypatch.setattr(module.shutil, "which",
                            lambda nom: "/usr/bin/python3.13" if nom == "python3.13" else None)
        monkeypatch.setattr(module, "antialiases", lambda _: True)
        assert module.a_smoothing_interpreter() == "/usr/bin/python3.13"

    def test_one_that_does_not_smooth_is_passed_over(self, under, monkeypatch):
        module = under("Linux", DISPLAY=":0")
        monkeypatch.setattr(module.shutil, "which",
                            lambda nom: f"/usr/bin/{nom}" if nom == "python3.13" else None)
        monkeypatch.setattr(module, "antialiases", lambda _: False)
        assert module.a_smoothing_interpreter() is None

    def test_elsewhere_the_shipped_tk_already_smooths(self, under, monkeypatch):
        """macOS and Windows: nothing to look for, and nothing to warn about."""
        for system in ("Darwin", "Windows"):
            module = under(system, DISPLAY=":0")
            assert module.a_smoothing_interpreter() is None


class TestTheCommandInThePath:
    """`greffier` lives in the repository's .venv, which no shell knows about.

    The installation announced "greffier fenetre" and the README repeats it;
    typed after an install that had just declared itself finished, the line
    answered "command not found".
    """

    @staticmethod
    def _an_environment(tmp_path):
        folder = tmp_path / "repository/.venv/bin"
        folder.mkdir(parents=True)
        (folder / "python").write_text("")
        launcher = folder / "greffier"
        launcher.write_text("")
        return folder / "python", launcher

    @staticmethod
    def _a_context(check_only=False):
        class Context:
            yes = True
            to_do: list[str] = []

            def __init__(self):
                self.check_only = check_only

            def ask(self, _question):
                return True

        return Context()

    def test_the_command_is_linked_where_the_shell_looks(self, under, monkeypatch, tmp_path):
        module = under("Linux")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        python, launcher = self._an_environment(tmp_path)

        module.etape_bureau(self._a_context(), python)

        link = tmp_path / ".local/bin/greffier"
        assert link.is_symlink(), "a link, so it follows the repository when the code changes"
        assert link.resolve() == launcher.resolve()

    def test_the_menu_entry_opens_the_window(self, under, monkeypatch, tmp_path):
        module = under("Linux")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        python, _ = self._an_environment(tmp_path)

        module.etape_bureau(self._a_context(), python)

        entry = tmp_path / ".local/share/applications/greffier.desktop"
        assert entry.exists(), "with no menu entry the window only opens from a terminal"
        assert f"Exec={tmp_path}/.local/bin/greffier fenetre" in entry.read_text(encoding="utf-8")

    def test_windows_is_told_where_the_command_is(self, under, monkeypatch, tmp_path, capsys):
        """No ~/.local/bin there, and the session PATH breaks more easily than it mends."""
        module = under("Windows")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        python, _ = self._an_environment(tmp_path)

        module.etape_bureau(self._a_context(), python)

        assert not (tmp_path / ".local/bin").exists()
        assert "PATH" in capsys.readouterr().out

    def test_checking_lays_nothing_down(self, under, monkeypatch, tmp_path):
        module = under("Linux")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        python, _ = self._an_environment(tmp_path)

        module.etape_bureau(self._a_context(check_only=True), python)

        assert not (tmp_path / ".local/bin/greffier").exists()
        assert not (tmp_path / ".local/share/applications/greffier.desktop").exists()

    def test_a_link_left_by_another_clone_is_replaced(self, under, monkeypatch, tmp_path):
        """A repository moved, and the old link points into the void."""
        module = under("Linux")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        python, launcher = self._an_environment(tmp_path)
        stale = tmp_path / ".local/bin/greffier"
        stale.parent.mkdir(parents=True)
        stale.symlink_to(tmp_path / "elsewhere/.venv/bin/greffier")

        module.etape_bureau(self._a_context(), python)

        assert stale.resolve() == launcher.resolve()


class TestMakingAFolder:
    """A folder is created; a dead link occupying its name is not a folder."""

    def test_a_link_that_leads_nowhere_is_removed(self, the_installer, tmp_path):
        link = tmp_path / "skills"
        link.symlink_to(tmp_path / "gone")
        the_installer.make_folder(link / "greffier")
        assert (link / "greffier").is_dir() and not link.is_symlink()

    def test_a_link_to_a_folder_that_exists_is_left_alone(self, the_installer, tmp_path):
        """It is a choice of the person installing, not a leftover."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        link = tmp_path / "skills"
        link.symlink_to(elsewhere)
        the_installer.make_folder(link / "greffier")
        assert link.is_symlink(), "a link that leads somewhere stays"
        assert (elsewhere / "greffier").is_dir()

    def test_an_existing_folder_is_kept_as_it_is(self, the_installer, tmp_path):
        already = tmp_path / "models"
        already.mkdir()
        (already / "titanet.onnx").write_bytes(b"x")
        the_installer.make_folder(already)
        assert (already / "titanet.onnx").exists()


class TestWhatTheConsoleCanShow:
    def test_the_symbols_have_an_ascii_fallback(self, the_installer):
        """A Windows console in cp1252 cannot write "✓"."""
        assert set(the_installer.SYMBOLES) == {"ok", "alerte", "erreur"}
        assert all(value for value in the_installer.SYMBOLES.values())

    def test_the_fallback_is_chosen_from_the_encoding(self, the_installer, monkeypatch):
        class NarrowConsole:
            encoding = "cp1252"

        monkeypatch.setattr(the_installer.sys, "stdout", NarrowConsole())
        assert the_installer._ecrivable("✓") is False
        assert the_installer._ecrivable("ok") is True


class TestCapturingSoundOnLinux:
    """What the installer judges the capture of the others' sound on.

    `pactl` records nothing: it queries the sound server, while ffmpeg plugs
    straight into its socket. Judging it absent announced an impossible capture on
    a machine perfectly able to do it, and sent people after a useless package.
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
        """A remote server puts no socket in this session."""
        module = under("Linux", XDG_RUNTIME_DIR=str(tmp_path),
                      PULSE_SERVER="tcp:192.168.1.10:4713")
        monkeypatch.setattr(module.shutil, "which", lambda _outil: None)

        assert module.sound_server_present()


class TestAccelerationByTheCard:
    """An NVIDIA card is not enough to accelerate the transcription.

    CTranslate2 asks for cuBLAS and cuDNN, which no distribution ships with the
    driver. Without them the transcription falls back on the processor, thirteen
    times real time as measured, which is thirteen hours for an hour of meeting.
    The installer therefore has to offer them, and only where they serve.
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
        """No NVIDIA card is usable there, and the chip already has Metal."""
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
        """The first cover of the template: the line could change in silence."""
        assert 'langue = "fr"' not in the_installer.GABARIT
        assert "langue = {langue!r}" in the_installer.GABARIT

    def test_the_language_catalogue_loads_without_the_package(self, the_installer):
        """The installer runs before anything at all is installed."""
        languages = the_installer._charger_langues()

        assert languages is not None
        assert ("fr", "Français") in languages.LANGUAGES


class TestAnEnvironmentInheritedFromBefore:
    """A `.venv` that came from another machine must not pass for valid.

    The measured case: a Linux image built from a macOS working copy. The `.venv`
    folder was copied, its links led nowhere, and the installer, which only looked
    at whether the folder existed, skipped creating it and then fell over on "No
    such file or directory: .venv/bin/python". The installation stopped there,
    which reads as "nothing works on Linux".
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
        """Reinstalling on every launch would cost minutes for nothing."""
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
        """Three lines further down, the Python traceback would have named no package."""
        self._prepare(the_installer, tmp_path, monkeypatch, avec_uv=False)
        context = type("Ctx", (), {"check_only": False, "to_do": [],
                                    "ask": lambda self, _q: False})()
        with pytest.raises(SystemExit):
            the_installer.etape_environnement(context, "whisper.cpp")


class TestWhetherTheVoiceIsThere:
    """Looking for "model.onnx" only ever held for Kokoro.

    A VITS names its weights after its voice. The installation therefore announced
    the voice as missing when it was in place, and offered to download eighty
    megabytes again on every run.
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
        """The model cannot be built without its tokens: better say so first."""
        (tmp_path / "fr_FR-upmc-medium.onnx").write_text("")
        assert not the_installer.voix_presente(tmp_path)

    def test_an_empty_folder_is_not_a_voice(self, the_installer, tmp_path):
        assert not the_installer.voix_presente(tmp_path)


class TestRoueCuda:
    """Quelle roue sherpa-onnx l'installation va chercher, système par système.

    Celle de PyPI ne sait pas parler à la carte, et il n'en existe pas sur PyPI
    qui le sache. Mesuré sur une réunion de 40,7 s, mêmes modèles et mêmes tours
    rendus : 43 s de découpage sur le processeur, 5,8 s sur la carte.
    """

    def test_linux_takes_the_wheel_built_with_onnxruntime(self, the_installer):
        url = the_installer.roue_cuda_sherpa("Linux", "cp313", "x86_64")
        assert url.endswith("onnxruntime1.27.1-cp313-cp313-linux_x86_64.whl")

    def test_windows_takes_another_naming(self, the_installer):
        url = the_installer.roue_cuda_sherpa("Windows", "cp313", "AMD64")
        assert url.endswith("cuda12.cudnn9-cp313-cp313-win_amd64.whl")

    def test_macos_has_no_nvidia_card(self, the_installer):
        assert the_installer.roue_cuda_sherpa("Darwin", "cp313", "arm64") is None

    def test_an_arm_machine_has_no_wheel(self, the_installer):
        """Un Raspberry ou un serveur Graviton : rien de publié pour eux."""
        assert the_installer.roue_cuda_sherpa("Linux", "cp313", "aarch64") is None

    def test_the_version_is_the_one_asked_for(self, the_installer):
        url = the_installer.roue_cuda_sherpa("Linux", "cp313", "x86_64")
        assert f"/{the_installer.SHERPA_CUDA}/" in url
        assert the_installer.SHERPA_CUDA in url.split("sherpa_onnx-")[1]

    def test_the_python_marker_is_carried(self, the_installer):
        url = the_installer.roue_cuda_sherpa("Linux", "cp314", "x86_64")
        assert "cp314-cp314" in url


class TestEtapeCarte:
    @pytest.fixture
    def travaux(self, the_installer, monkeypatch):
        faits = []
        monkeypatch.setattr(
            the_installer, "run_job",
            lambda commande, **_k: faits.append(commande) or _Fini(),
        )
        monkeypatch.setattr(the_installer, "_marqueur_python", lambda _p: ("cp313", "x86_64"))
        return faits

    def test_a_machine_without_a_card_installs_nothing(
        self, the_installer, monkeypatch, travaux
    ):
        monkeypatch.setattr(the_installer, "carte_nvidia", lambda: False)
        the_installer.etape_carte(_Demande(), "python")
        assert travaux == []

    def test_macos_is_never_asked(self, under, monkeypatch, travaux):
        """Apple a cessé de porter NVIDIA avec Mojave : il n'y a rien à accélérer."""
        module = under("Darwin")
        monkeypatch.setattr(module, "shutil", _AvecNvidiaSmi())
        module.etape_carte(_Demande(), "python")
        assert travaux == []

    def test_linux_with_a_card_takes_the_wheel(self, under, monkeypatch, travaux):
        module = under("Linux")
        monkeypatch.setattr(module, "carte_nvidia", lambda: True)
        module.etape_carte(_Demande(), "python")
        assert len(travaux) == 1
        assert travaux[0][-1].endswith("linux_x86_64.whl")

    def test_windows_with_a_card_takes_its_own(self, under, monkeypatch, travaux):
        module = under("Windows")
        monkeypatch.setattr(module, "carte_nvidia", lambda: True)
        module.etape_carte(_Demande(), "python")
        assert travaux[0][-1].endswith("win_amd64.whl")

    def test_an_interpreter_that_will_not_answer_stops_there(
        self, under, monkeypatch, travaux
    ):
        module = under("Linux")
        monkeypatch.setattr(module, "carte_nvidia", lambda: True)
        monkeypatch.setattr(module, "_marqueur_python", lambda _p: (None, None))
        module.etape_carte(_Demande(), "python")
        assert travaux == []

    def test_a_refusal_leaves_the_command_to_run_later(self, under, monkeypatch, travaux):
        module = under("Linux")
        monkeypatch.setattr(module, "carte_nvidia", lambda: True)
        demande = _Demande()
        demande.reponse = False
        module.etape_carte(demande, "python")
        assert travaux == []
        assert demande.to_do and demande.to_do[0].startswith("uv pip install")


class _Fini:
    returncode = 0


class _AvecNvidiaSmi:
    """Une machine qui porte l'outil NVIDIA, ce qui ne suffit pas sous macOS."""

    @staticmethod
    def which(_name):
        return "/usr/bin/nvidia-smi"


class _Demande:
    """Ce que l'installation passe en contexte, réduit à ce qui sert ici."""

    check_only = False
    yes = True

    def __init__(self) -> None:
        self.to_do = []
        self.reponse = True

    def ask(self, _question):
        return self.reponse
