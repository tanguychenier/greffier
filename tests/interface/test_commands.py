"""The names of the commands, which are what people type and what the tool runs.

A command name is displayed text: it stays French, and it must not follow the
Python identifier around. The defect that called for this file: renaming the
`veiller` function to `watch` renamed the command with it, because the decorator
had no name of its own. Nothing failed loudly — `greffier enregistrer` went on
launching `greffier veiller` in a detached process, which died at once on *No
such command*, and the hardware watch was gone from every meeting recorded
since.
"""

import ast
import re
from pathlib import Path

import pytest

from greffier.cli import application

SOURCE = Path(__file__).resolve().parents[2] / "src" / "greffier" / "cli.py"


def command_names() -> set[str]:
    return {command.name for command in application.registered_commands if command.name}


class TestWhatTheToolLaunchesItself:
    """Read from the source, so that a new launch is covered the day it is written."""

    @staticmethod
    def launched() -> list[str]:
        code = SOURCE.read_text(encoding="utf-8")
        return re.findall(
            r'\[sys\.executable,\s*"-m",\s*"greffier",\s*"([a-z-]+)"\]', code)

    def test_there_is_something_to_check(self):
        assert self.launched()

    @pytest.mark.parametrize("name", launched.__func__())
    def test_the_command_exists(self, name):
        assert name in command_names()


class TestANameIsNeverInherited:
    """Without an explicit name, Typer takes the function's, and renaming the
    function renames the command."""

    def test_every_command_is_named_in_its_decorator(self):
        arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
        sans_nom = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            for decorateur in noeud.decorator_list:
                if not isinstance(decorateur, ast.Call):
                    continue
                cible = decorateur.func
                if not (isinstance(cible, ast.Attribute) and cible.attr == "command"):
                    continue
                nomme = bool(decorateur.args) or any(
                    mot.arg == "name" for mot in decorateur.keywords)
                if not nomme:
                    sans_nom.append(noeud.name)
        assert sans_nom == []


class TestTheNamesStayFrench:
    """The command line is what the tool shows: it is typed by people."""

    def test_no_name_is_an_english_word_of_the_code(self):
        assert not command_names() & {"watch", "record", "process", "send",
                                       "window", "assist", "check", "stop"}

    def test_the_hardware_watch_answers_to_its_name(self):
        assert "veiller" in command_names()
