"""The Claude Code account, read from the session file.

That account is the one writing: without a session everything works except
the minutes, and the failure would only show after the transcription. The
Settings tab shows it, so the read has to be free, instant, and never fall
on an absent or damaged file.
"""

import json

import pytest

from greffier.adapters import system_diagnostic as diagnostic


@pytest.fixture
def a_clean_home(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def write(a_clean_home, content):
    (a_clean_home / ".claude.json").write_text(json.dumps(content), encoding="utf-8")


class TestReadingTheAccount:
    def test_the_signed_in_account_is_recognised(self, a_clean_home):
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme",
                                         "seatTier": "team_tier_1"}})
        count = diagnostic.claude_account()
        assert count is not None
        assert count.address == "moi@exemple.fr"
        assert count.organisation == "Acme"
        assert count.phrasing == "team_tier_1"

    def test_the_display_joins_address_and_organisation(self, a_clean_home):
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme"}})
        assert str(diagnostic.claude_account()) == "moi@exemple.fr · Acme"

    def test_a_session_with_no_details_is_still_a_session(self, a_clean_home):
        """The file may carry an identifier without a profile: that is signed in."""
        write(a_clean_home, {"userID": "abc"})
        count = diagnostic.claude_account()
        assert count is not None and str(count) == "session ouverte"

    def test_no_file_means_no_session(self, a_clean_home):
        assert diagnostic.claude_account() is None

    def test_a_damaged_file_does_not_bring_the_window_down(self, a_clean_home):
        (a_clean_home / ".claude.json").write_text("{ pas du json", encoding="utf-8")
        assert diagnostic.claude_account() is None

    def test_a_file_with_neither_account_nor_identifier(self, a_clean_home):
        write(a_clean_home, {"autreChose": 1})
        assert diagnostic.claude_account() is None


class TestWhatIsNeverRead:
    def test_no_token_is_touched(self, a_clean_home):
        """The window shows enough to recognise the account, nothing secret."""
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "accessToken": "secret-à-ne-jamais-lire"}})
        count = diagnostic.claude_account()
        assert count is not None
        champs = (count.address, count.organisation, count.phrasing)
        assert not any("secret" in value for value in champs)
        assert not hasattr(count, "accessToken")

    def test_the_reading_never_goes_through_the_network(self, a_clean_home, monkeypatch):
        """A network call would make the tab wait to open for nothing."""
        def forbidden_one(*_args, **_options):
            raise AssertionError("aucun sous-processus ne doit être lancé")

        monkeypatch.setattr(diagnostic.subprocess, "run", forbidden_one)
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr"}})
        assert diagnostic.claude_account() is not None
