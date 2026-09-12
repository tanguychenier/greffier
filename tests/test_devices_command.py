"""The command that builds the two macOS audio devices.

It used to fall back, when no microphone was named, on a device written into the
Swift script: the headset of the machine where that script was written. On any
other Mac the command then looked for hardware nobody has, in order to announce
that it could not find it.
"""

from __future__ import annotations

import platform

import pytest
from typer.testing import CliRunner

from greffier.cli import application

runner = CliRunner()


@pytest.fixture
def sur_macos(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")


@pytest.fixture
def swift(monkeypatch):
    """Catches what would have been run, and runs nothing."""
    lances: list[list[str]] = []

    class Lu:
        returncode = 0

    monkeypatch.setattr(
        "subprocess.run", lambda arguments, **k: lances.append(arguments) or Lu()
    )
    return lances


class TestElsewhereThanMacOS:
    def test_it_says_the_system_already_has_what_is_needed(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        answered = runner.invoke(application, ["peripheriques"])
        assert answered.exit_code == 0
        assert "moniteur de sortie" in answered.stdout


class TestWhichMicrophoneIsUsed:
    def test_the_one_the_command_names(self, sur_macos, swift, tmp_path):
        runner.invoke(application, ["peripheriques", "--micro", "Shure MV7"])
        assert swift and "--mic" in swift[0]
        assert swift[0][swift[0].index("--mic") + 1] == "Shure MV7"

    def test_failing_that_the_one_in_the_settings(self, sur_macos, swift, tmp_path):
        """A microphone chosen once in the window is a microphone chosen."""
        reglages = tmp_path / "config.toml"
        reglages.write_text('[audio]\nmicro = "Rode NT-USB"\n', encoding="utf-8")
        runner.invoke(application, ["peripheriques", "--config", str(reglages)])
        assert swift[0][swift[0].index("--mic") + 1] == "Rode NT-USB"

    def test_with_neither_it_refuses_rather_than_guesses(
            self, sur_macos, swift, tmp_path):
        reglages = tmp_path / "config.toml"
        reglages.write_text("[audio]\n", encoding="utf-8")
        answered = runner.invoke(
            application, ["peripheriques", "--config", str(reglages)])
        assert answered.exit_code == 1
        # Sur la sortie d'erreur : c'en est une, et un script qui appelle la
        # commande doit pouvoir séparer le message du reste.
        assert "aucun micro" in answered.stderr
        assert not swift, "rien ne doit être lancé sans savoir quoi chercher"

    def test_listing_needs_no_microphone(self, sur_macos, swift, tmp_path):
        """Asking what exists is precisely what one does when one does not know."""
        reglages = tmp_path / "config.toml"
        reglages.write_text("[audio]\n", encoding="utf-8")
        answered = runner.invoke(
            application, ["peripheriques", "--lister", "--config", str(reglages)])
        assert answered.exit_code == 0
        assert "--list" in swift[0]


class TestTheSwiftScriptCarriesNoHardware:
    def test_no_device_name_is_written_into_it(self):
        """The name of one desk's headset is not a default for everyone else's."""
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "macos/creer-peripheriques.swift"
        texte = source.read_text(encoding="utf-8")
        assert 'option("--mic", "")' in texte
        assert "Jabra" not in texte
