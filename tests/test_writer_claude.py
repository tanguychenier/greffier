"""The call to the writing assistant: what leaves on the command line.

The model is passed explicitly. Without that, the tool would follow the personal
setting of whoever installed it: the minutes would change writer with nobody
deciding it, and could eat the top of the range where the second one is enough.
"""

import subprocess

import pytest

from greffier.adapters.writer_claude import ClaudeWriter


@pytest.fixture
def spy(monkeypatch):
    """Keeps the command launched, without ever calling the assistant."""
    vu: dict[str, list[str]] = {}

    def faux_run(command, **options):
        vu["commande"] = list(command)
        vu["entree"] = options.get("input", "")
        return subprocess.CompletedProcess(command, 0, stdout="# Compte rendu\n", stderr="")

    monkeypatch.setattr("greffier.adapters.writer_claude.shutil.which",
                        lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr("greffier.adapters.writer_claude.subprocess.run", faux_run)
    return vu


class TestModele:
    def test_the_model_asked_for_is_passed_on(self, spy):
        ClaudeWriter("opus").write_up("Sandy : bonjour.")
        assert "--model" in spy["commande"]
        assert spy["commande"][spy["commande"].index("--model") + 1] == "opus"

    def test_with_no_model_nothing_is_imposed(self, spy):
        """Useful to exercise the tool exactly as the machine is set up."""
        ClaudeWriter().write_up("Sandy : bonjour.")
        assert "--model" not in spy["commande"]

    def test_the_transcription_goes_through_standard_input(self, spy):
        """An hour of transcription is bigger than an argument may be."""
        ClaudeWriter("opus").write_up("Sandy : bonjour.")
        assert "Sandy : bonjour." in spy["entree"]
        assert not any("Sandy" in morceau for morceau in spy["commande"])

    def test_no_tool_is_allowed(self, spy):
        """Le rédacteur écrit un document, il n'a rien à lire ni à exécuter."""
        command = spy if False else None
        ClaudeWriter("opus").write_up("x")
        assert "--allowed-tools" in spy["commande"]
        assert spy["commande"][spy["commande"].index("--allowed-tools") + 1] == ""
        assert command is None


class TestWhenThingsFail:
    def test_a_missing_writer_says_so_and_offers_the_fix(self, monkeypatch):
        monkeypatch.setattr("greffier.adapters.writer_claude.shutil.which",
                            lambda _name: None)
        with pytest.raises(RuntimeError, match="ollama"):
            ClaudeWriter("opus").write_up("x")

    def test_an_empty_output_is_an_error(self, monkeypatch):
        monkeypatch.setattr("greffier.adapters.writer_claude.shutil.which",
                            lambda _name: "/usr/local/bin/claude")
        monkeypatch.setattr(
            "greffier.adapters.writer_claude.subprocess.run",
            lambda command, **o: subprocess.CompletedProcess(command, 0, "", "quota atteint"),
        )
        with pytest.raises(RuntimeError, match="quota atteint"):
            ClaudeWriter("opus").write_up("x")


class TestTheMachinesOwnServersStayOut:
    """The assistant of a meeting has no business loading them.

    A machine may carry any number of MCP servers, declared for other work
    entirely. Loading them into the call that writes the minutes gives them
    reach over what was said in the room, and measured over seven runs it also
    costs 0.3 s on a round trip of 3.
    """

    def test_only_the_configuration_given_is_used(self, spy):
        ClaudeWriter().write_up("Sandy : bonjour.")
        assert "--strict-mcp-config" in spy["commande"]
