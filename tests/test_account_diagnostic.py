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
def maison(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def write(maison, content):
    (maison / ".claude.json").write_text(json.dumps(content), encoding="utf-8")


class TestLectureDuCompte:
    def test_le_compte_connecte_est_reconnu(self, maison):
        write(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme",
                                         "seatTier": "team_tier_1"}})
        count = diagnostic.claude_account()
        assert count is not None
        assert count.adresse == "moi@exemple.fr"
        assert count.organisation == "Acme"
        assert count.formule == "team_tier_1"

    def test_l_affichage_joint_adresse_et_organisation(self, maison):
        write(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme"}})
        assert str(diagnostic.claude_account()) == "moi@exemple.fr · Acme"

    def test_une_session_sans_details_reste_une_session(self, maison):
        """Le fichier peut porter un identifiant sans profil : c'est connecté."""
        write(maison, {"userID": "abc"})
        count = diagnostic.claude_account()
        assert count is not None and str(count) == "session ouverte"

    def test_aucun_fichier_veut_dire_aucune_session(self, maison):
        assert diagnostic.claude_account() is None

    def test_un_fichier_abime_ne_fait_pas_tomber_la_fenetre(self, maison):
        (maison / ".claude.json").write_text("{ pas du json", encoding="utf-8")
        assert diagnostic.claude_account() is None

    def test_un_fichier_sans_compte_ni_identifiant(self, maison):
        write(maison, {"autreChose": 1})
        assert diagnostic.claude_account() is None


class TestCeQuiNEstPasLu:
    def test_aucun_jeton_n_est_touche(self, maison):
        """La fenêtre affiche de quoi reconnaître le compte, rien de secret."""
        write(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "accessToken": "secret-à-ne-jamais-lire"}})
        count = diagnostic.claude_account()
        assert count is not None
        champs = (count.adresse, count.organisation, count.formule)
        assert not any("secret" in value for value in champs)
        assert not hasattr(count, "accessToken")

    def test_la_lecture_ne_passe_pas_par_le_reseau(self, maison, monkeypatch):
        """Un appel réseau ferait attendre l'ouverture de l'onglet pour rien."""
        def interdit(*_args, **_options):
            raise AssertionError("aucun sous-processus ne doit être lancé")

        monkeypatch.setattr(diagnostic.subprocess, "run", interdit)
        write(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr"}})
        assert diagnostic.claude_account() is not None
