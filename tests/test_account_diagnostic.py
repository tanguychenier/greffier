"""Le compte Claude Code, lu du fichier de session.

C'est ce compte qui rédige : sans session, tout fonctionne sauf le compte
rendu, et l'échec n'apparaîtrait qu'après la transcription. L'onglet Réglages
l'affiche, donc la lecture doit être gratuite, instantanée, et ne jamais tomber
sur un fichier absent ou abîmé.
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
        assert count.adresse == "moi@exemple.fr"
        assert count.organisation == "Acme"
        assert count.formule == "team_tier_1"

    def test_l_affichage_joint_adresse_et_organisation(self, a_clean_home):
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme"}})
        assert str(diagnostic.claude_account()) == "moi@exemple.fr · Acme"

    def test_a_session_with_no_details_is_still_a_session(self, a_clean_home):
        """Le fichier peut porter un identifiant sans profil : c'est connecté."""
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
        """La fenêtre affiche de quoi reconnaître le compte, rien de secret."""
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "accessToken": "secret-à-ne-jamais-lire"}})
        count = diagnostic.claude_account()
        assert count is not None
        champs = (count.adresse, count.organisation, count.formule)
        assert not any("secret" in value for value in champs)
        assert not hasattr(count, "accessToken")

    def test_the_reading_never_goes_through_the_network(self, a_clean_home, monkeypatch):
        """Un appel réseau ferait attendre l'ouverture de l'onglet pour rien."""
        def interdit(*_args, **_options):
            raise AssertionError("aucun sous-processus ne doit être lancé")

        monkeypatch.setattr(diagnostic.subprocess, "run", interdit)
        write(a_clean_home, {"oauthAccount": {"emailAddress": "moi@exemple.fr"}})
        assert diagnostic.claude_account() is not None
