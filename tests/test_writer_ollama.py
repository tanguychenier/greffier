"""The Ollama writer without a server: what it refuses before any call leaves."""

import pytest

from greffier.adapters.writer_ollama import OllamaWriter


class TestTheHost:
    def test_the_loopback_default_passes(self):
        assert OllamaWriter("mistral").host == "http://127.0.0.1:11434"

    def test_a_trailing_slash_is_dropped(self):
        assert OllamaWriter("mistral", host="http://serveur:11434/").host == "http://serveur:11434"

    def test_an_address_without_http_is_refused(self):
        """urlopen would otherwise read whatever the address names, a file included."""
        with pytest.raises(ValueError, match=r"http\(s\)://"):
            OllamaWriter("mistral", host="file:///etc/passwd")
