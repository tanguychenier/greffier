"""The registry of sources in a file, and the tokens out of that file."""

from pathlib import Path

import pytest

from greffier.adapters import sources_file
from greffier.domain.sources import Kind, Right, Source


@pytest.fixture
def file(tmp_path: Path) -> Path:
    return tmp_path / "sources.toml"


def write(file: Path, content: str) -> Path:
    file.write_text(content, encoding="utf-8")
    return file


class TestTheTemplateFile:
    def test_the_template_is_laid_down_when_the_file_is_missing(self, file):
        assert sources_file.lay_the_template(file)
        assert file.exists()

    def test_it_never_overwrites_an_existing_file(self, file):
        """The registry is written by hand: overwriting it would lose accesses."""
        write(file, "# le mien\n")
        assert not sources_file.lay_the_template(file)
        assert file.read_text(encoding="utf-8") == "# le mien\n"

    def test_the_template_declares_no_source(self, file):
        """Rien n'est atteignable avant qu'un humain l'inscrive."""
        sources_file.lay_the_template(file)
        assert sources_file.read(file).sources == []

    def test_the_template_says_where_to_put_the_token_not_the_token(self, file):
        sources_file.lay_the_template(file)
        said = file.read_text(encoding="utf-8")
        assert "trousseau:" in said
        assert "security add-generic-password" in said


class TestReadingTheSourcesFile:
    def test_a_missing_file_gives_no_source(self, file):
        assert sources_file.read(file).sources == []

    def test_an_unreadable_file_does_not_bring_it_down(self, file):
        write(file, "ceci n'est pas du TOML [[[")
        assert sources_file.read(file).sources == []

    def test_a_registered_source_is_read(self, file):
        write(file, """
[[sources]]
nom = "recherche"
genre = "gitlab"
adresse = "https://gitlab.example.fr"
projet = "equipe/outil"
jeton = "GREFFIER_GITLAB_JETON"
""")
        source = sources_file.read(file).sources[0]
        assert source.name == "recherche"
        assert source.kind is Kind.GITLAB
        assert source.project == "equipe/outil"

    def test_read_only_is_the_default_of_the_file(self, file):
        write(file, """
[[sources]]
nom = "x"
genre = "jira"
adresse = "https://x.atlassian.net"
projet = "PROJ"
""")
        assert not sources_file.read(file).sources[0].can_write

    def test_writing_is_declared_explicitly(self, file):
        write(file, """
[[sources]]
nom = "x"
genre = "jira"
adresse = "https://x.atlassian.net"
projet = "PROJ"
droit = "écriture"
""")
        assert sources_file.read(file).sources[0].droit is Right.ECRITURE

    def test_the_trailing_slash_of_the_address_is_removed(self, file):
        """Sinon l'appel vise « …fr//api/v4 », que GitLab refuse."""
        write(file, """
[[sources]]
nom = "x"
genre = "gitlab"
adresse = "https://gitlab.example.fr/"
projet = "a/b"
""")
        assert sources_file.read(file).sources[0].adresse.endswith(".fr")

    def test_an_invalid_entry_is_dropped_without_losing_the_others(self, file):
        write(file, """
[[sources]]
nom = "cassee"
genre = "gitlab"
adresse = "pas-une-adresse"
projet = "a/b"

[[sources]]
nom = "bonne"
genre = "gitlab"
adresse = "https://gitlab.example.fr"
projet = "a/b"
""")
        assert sources_file.read(file).recorded() == ["bonne"]

    def test_an_unknown_kind_is_dropped(self, file):
        """« github » is not wired: better absent than half done."""
        write(file, """
[[sources]]
nom = "x"
genre = "github"
adresse = "https://github.com"
projet = "a/b"
""")
        assert sources_file.read(file).sources == []


class TestWhereTheTokenComesFrom:
    def test_an_environment_variable_is_read(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_ESSAI_JETON", "glpat-secret")
        source = Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                        project="a/b", token="GREFFIER_ESSAI_JETON")
        assert sources_file.token_for(source) == "glpat-secret"

    def test_a_missing_variable_does_not_raise(self, monkeypatch):
        """A missing token is a setting to finish, not a breakdown."""
        monkeypatch.delenv("GREFFIER_ABSENT", raising=False)
        source = Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                        project="a/b", token="GREFFIER_ABSENT")
        assert sources_file.token_for(source) == ""

    def test_a_source_with_no_declared_token_returns_nothing(self):
        source = Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                        project="a/b")
        assert sources_file.token_for(source) == ""

    def test_the_keychain_is_asked_for_the_prefix(self, monkeypatch):
        appels: list[list[str]] = []

        def render(command, **_options):
            appels.append(command)
            return type("Fait", (), {"returncode": 0, "stdout": "du-trousseau\n"})()

        monkeypatch.setattr(sources_file.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(sources_file.shutil, "which", lambda _n: "/usr/bin/security")
        monkeypatch.setattr(sources_file.subprocess, "run", render)
        source = Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                        project="a/b", token="trousseau:greffier-gitlab")
        assert sources_file.token_for(source) == "du-trousseau"
        assert "greffier-gitlab" in appels[0]

    def test_a_keychain_that_refuses_returns_nothing(self, monkeypatch):
        monkeypatch.setattr(sources_file.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(sources_file.shutil, "which", lambda _n: "/usr/bin/security")
        monkeypatch.setattr(
            sources_file.subprocess, "run",
            lambda *_a, **_k: type("Fait", (), {"returncode": 44, "stdout": ""})(),
        )
        source = Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                        project="a/b", token="trousseau:absent")
        assert sources_file.token_for(source) == ""

    def test_outside_macos_the_keychain_is_not_called(self, monkeypatch):
        def jamais(*_a, **_k):
            raise AssertionError("security n'existe pas ici")

        monkeypatch.setattr(sources_file.platform, "system", lambda: "Linux")
        monkeypatch.setattr(sources_file.subprocess, "run", jamais)
        source = Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                        project="a/b", token="trousseau:x")
        assert sources_file.token_for(source) == ""


class TestTheTokensTheWindowStores:
    """A token pasted into the window goes to a file of the user's own, next
    to the registry, under the name the registry gives it."""

    def _source(self, token="GREFFIER_ESSAI_JETON"):
        return Source(name="x", kind=Kind.GITLAB, adresse="https://x.fr",
                      project="a/b", token=token)

    def test_a_stored_token_is_found_when_the_environment_has_none(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("GREFFIER_ESSAI_JETON", raising=False)
        file = tmp_path / "jetons.toml"
        sources_file.store_token(file, "GREFFIER_ESSAI_JETON", "glpat-fenetre")
        assert sources_file.token_for(self._source(), file) == "glpat-fenetre"

    def test_the_environment_wins_over_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GREFFIER_ESSAI_JETON", "glpat-terminal")
        file = tmp_path / "jetons.toml"
        sources_file.store_token(file, "GREFFIER_ESSAI_JETON", "glpat-fenetre")
        assert sources_file.token_for(self._source(), file) == "glpat-terminal"

    def test_the_file_belongs_to_the_user_alone(self, tmp_path):
        import os
        import stat

        if os.name != "posix":
            pytest.skip("file modes are a posix thing")
        file = tmp_path / "jetons.toml"
        sources_file.store_token(file, "A", "secret")
        assert stat.S_IMODE(file.stat().st_mode) == 0o600

    def test_several_tokens_live_side_by_side(self, tmp_path):
        file = tmp_path / "jetons.toml"
        sources_file.store_token(file, "A", "un")
        sources_file.store_token(file, "B", 'deux "avec" guillemets')
        assert sources_file.stored_tokens(file) == {"A": "un", "B": 'deux "avec" guillemets'}

    def test_an_empty_secret_removes_the_token(self, tmp_path):
        file = tmp_path / "jetons.toml"
        sources_file.store_token(file, "A", "un")
        sources_file.store_token(file, "A", "")
        assert sources_file.stored_tokens(file) == {}

    def test_a_damaged_file_gives_nothing_rather_than_an_error(self, tmp_path):
        file = tmp_path / "jetons.toml"
        file.write_text("[jetons\nA = ", encoding="utf-8")
        assert sources_file.stored_tokens(file) == {}

    def test_the_file_sits_next_to_the_registry(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setattr("platform.system", lambda: "Linux")
        assert sources_file.tokens_file() == tmp_path / "greffier" / "jetons.toml"
