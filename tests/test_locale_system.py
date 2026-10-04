"""The machine's language is read without the API Python 3.15 removes.

`locale.getdefaultlocale` was called twice in this adapter, deprecated since
Python 3.11 and gone in 3.15: one test run printed its warning 86 times. On
POSIX the environment is the whole locale, so nothing replaces the call; on
Windows the user's locale has a name kernel32 gives directly, `fr-FR`, and the
domain expects it as `fr_FR` like every other system's answer.
"""

from __future__ import annotations

import ctypes
import subprocess
import warnings

import pytest

from greffier.adapters import locale_system

VARIABLES = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")


class _Kernel32:
    """kernel32 as far as this adapter asks it: one function, one answer."""

    def __init__(self, name: str | None):
        self.name = name
        self.sizes_asked: list[int] = []

    def GetUserDefaultLocaleName(self, buffer, size):
        self.sizes_asked.append(size)
        if self.name is None:
            return 0
        buffer.value = self.name
        return len(self.name) + 1


class _Windll:
    def __init__(self, kernel32: _Kernel32):
        self.kernel32 = kernel32


@pytest.fixture
def silent_shell(monkeypatch):
    """No variable says anything: the system itself has to be asked."""
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def windows(monkeypatch, silent_shell):  # noqa: ARG001  # pytest wires fixtures by name
    """A Windows whose kernel32 answers what the test tells it to."""
    monkeypatch.setattr(locale_system, "SYSTEM", "Windows")

    def whose_locale_is(name: str | None) -> _Kernel32:
        kernel32 = _Kernel32(name)
        monkeypatch.setattr(ctypes, "windll", _Windll(kernel32), raising=False)
        return kernel32

    return whose_locale_is


def _never_asked(*_):
    raise AssertionError("the system was asked although the shell had answered")


class TestTheShellIsBelievedFirst:
    @pytest.mark.usefixtures("silent_shell")
    def test_lc_all_wins_over_lang(self, monkeypatch):
        monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
        monkeypatch.setenv("LANG", "fr_FR.UTF-8")
        assert locale_system.read() == "de_DE.UTF-8"

    @pytest.mark.usefixtures("silent_shell")
    def test_a_list_of_languages_gives_its_first(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr_FR:en_GB")
        assert locale_system.read() == "fr_FR"

    @pytest.mark.usefixtures("silent_shell")
    def test_c_and_posix_are_not_languages(self, monkeypatch):
        monkeypatch.setattr(locale_system, "SYSTEM", "Linux")
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "POSIX")
        assert locale_system.read() == ""

    @pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
    @pytest.mark.usefixtures("silent_shell")
    def test_the_shell_beats_every_system(self, monkeypatch, system):
        monkeypatch.setattr(locale_system, "SYSTEM", system)
        monkeypatch.setattr(locale_system, "_from_macos", _never_asked)
        monkeypatch.setattr(locale_system, "_windows_user_locale_name", _never_asked)
        monkeypatch.setenv("LANG", "fr_FR.UTF-8")
        assert locale_system.read() == "fr_FR.UTF-8"

    def test_windows_is_not_even_asked_when_the_shell_answers(self, monkeypatch, windows):
        kernel32 = windows("en-US")
        monkeypatch.setenv("LANG", "fr_FR.UTF-8")
        assert locale_system.read() == "fr_FR.UTF-8"
        assert kernel32.sizes_asked == []


class TestWindowsIsAskedThroughKernel32:
    def test_the_name_windows_gives_takes_the_shape_of_the_others(self, windows):
        windows("fr-FR")
        assert locale_system.read() == "fr_FR"

    def test_a_name_with_a_script_keeps_every_part(self, windows):
        windows("zh-Hans-CN")
        assert locale_system.read() == "zh_Hans_CN"

    def test_the_buffer_offered_is_the_longest_name_windows_allows(self, windows):
        """85 is LOCALE_NAME_MAX_LENGTH in the Windows headers, terminator included."""
        kernel32 = windows("fr-FR")
        locale_system.read()
        assert kernel32.sizes_asked == [85]

    def test_a_kernel32_that_writes_nothing_gives_an_empty_string(self, windows):
        windows(None)
        assert locale_system.read() == ""

    def test_a_kernel32_that_raises_gives_an_empty_string(self, monkeypatch, windows):
        kernel32 = windows("fr-FR")

        def broken(*_):
            raise OSError("kernel32 not found")

        monkeypatch.setattr(kernel32, "GetUserDefaultLocaleName", broken)
        assert locale_system.read() == ""

    @pytest.mark.usefixtures("silent_shell")
    def test_a_python_without_windll_has_no_windows_to_ask(self, monkeypatch):
        """Everywhere but Windows `ctypes.windll` does not exist; nothing is invented."""
        monkeypatch.setattr(locale_system, "SYSTEM", "Windows")
        monkeypatch.delattr(ctypes, "windll", raising=False)
        assert locale_system.read() == ""

    @pytest.mark.usefixtures("silent_shell")
    def test_whatever_the_reader_answers_is_normalised(self, monkeypatch):
        monkeypatch.setattr(locale_system, "SYSTEM", "Windows")
        monkeypatch.setattr(locale_system, "_windows_user_locale_name", lambda: "de-AT")
        assert locale_system.read() == "de_AT"


class TestMacosIsAskedThroughDefaults:
    @pytest.fixture
    def macos(self, monkeypatch, silent_shell):  # noqa: ARG002  # wired by name
        monkeypatch.setattr(locale_system, "SYSTEM", "Darwin")

        def whose_defaults(answer):
            monkeypatch.setattr(locale_system.subprocess, "run", answer)

        return whose_defaults

    def test_the_apple_locale_is_read(self, macos):
        def defaults(command, **_):
            assert command == ["defaults", "read", "-g", "AppleLocale"]
            return subprocess.CompletedProcess(command, 0, stdout="fr_CA\n", stderr="")

        macos(defaults)
        assert locale_system.read() == "fr_CA"

    def test_a_defaults_that_fails_gives_an_empty_string(self, macos):
        def defaults(command, **_):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="no such key")

        macos(defaults)
        assert locale_system.read() == ""

    def test_a_machine_without_defaults_gives_an_empty_string(self, macos):
        def defaults(_command, **_):
            raise FileNotFoundError("defaults")

        macos(defaults)
        assert locale_system.read() == ""

    def test_a_defaults_that_hangs_gives_an_empty_string(self, macos):
        def defaults(command, **_):
            raise subprocess.TimeoutExpired(command, 5)

        macos(defaults)
        assert locale_system.read() == ""


class TestPosixHasNothingElseToRead:
    @pytest.mark.usefixtures("silent_shell")
    def test_a_silent_shell_is_an_empty_answer(self, monkeypatch):
        """The C library reads the same variables: when they say nothing, nothing does."""
        monkeypatch.setattr(locale_system, "SYSTEM", "Linux")
        assert locale_system.read() == ""


class TestNothingDeprecatedIsCalled:
    @pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
    @pytest.mark.usefixtures("silent_shell")
    def test_reading_emits_no_warning_on_any_system(self, monkeypatch, system):
        """`locale.getdefaultlocale` warned 86 times a run; here a warning is an error."""
        monkeypatch.setattr(locale_system, "SYSTEM", system)
        monkeypatch.setattr(locale_system, "_from_macos", lambda: "")
        monkeypatch.delattr(ctypes, "windll", raising=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("error")
            assert locale_system.read() == ""
        assert caught == []
