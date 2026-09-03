"""Le compte Claude Code, lu du fichier de session.

C'est ce compte qui rédige : sans session, tout fonctionne sauf le compte
rendu, et l'échec n'apparaîtrait qu'après la transcription. L'onglet Réglages
l'affiche, donc la lecture doit être gratuite, instantanée, et ne jamais tomber
sur un fichier absent ou abîmé.
"""

import json

import pytest

from greffier import diagnostic


@pytest.fixture
def maison(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def ecrire(maison, contenu):
    (maison / ".claude.json").write_text(json.dumps(contenu), encoding="utf-8")


class TestLectureDuCompte:
    def test_le_compte_connecte_est_reconnu(self, maison):
        ecrire(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme",
                                         "seatTier": "team_tier_1"}})
        compte = diagnostic.compte_claude()
        assert compte is not None
        assert compte.adresse == "moi@exemple.fr"
        assert compte.organisation == "Acme"
        assert compte.formule == "team_tier_1"

    def test_l_affichage_joint_adresse_et_organisation(self, maison):
        ecrire(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "organizationName": "Acme"}})
        assert str(diagnostic.compte_claude()) == "moi@exemple.fr · Acme"

    def test_une_session_sans_details_reste_une_session(self, maison):
        """Le fichier peut porter un identifiant sans profil : c'est connecté."""
        ecrire(maison, {"userID": "abc"})
        compte = diagnostic.compte_claude()
        assert compte is not None and str(compte) == "session ouverte"

    def test_aucun_fichier_veut_dire_aucune_session(self, maison):
        assert diagnostic.compte_claude() is None

    def test_un_fichier_abime_ne_fait_pas_tomber_la_fenetre(self, maison):
        (maison / ".claude.json").write_text("{ pas du json", encoding="utf-8")
        assert diagnostic.compte_claude() is None

    def test_un_fichier_sans_compte_ni_identifiant(self, maison):
        ecrire(maison, {"autreChose": 1})
        assert diagnostic.compte_claude() is None


class TestCeQuiNEstPasLu:
    def test_aucun_jeton_n_est_touche(self, maison):
        """La fenêtre affiche de quoi reconnaître le compte, rien de secret."""
        ecrire(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr",
                                         "accessToken": "secret-à-ne-jamais-lire"}})
        compte = diagnostic.compte_claude()
        assert compte is not None
        champs = (compte.adresse, compte.organisation, compte.formule)
        assert not any("secret" in valeur for valeur in champs)
        assert not hasattr(compte, "accessToken")

    def test_la_lecture_ne_passe_pas_par_le_reseau(self, maison, monkeypatch):
        """Un appel réseau ferait attendre l'ouverture de l'onglet pour rien."""
        def interdit(*_args, **_options):
            raise AssertionError("aucun sous-processus ne doit être lancé")

        monkeypatch.setattr(diagnostic.subprocess, "run", interdit)
        ecrire(maison, {"oauthAccount": {"emailAddress": "moi@exemple.fr"}})
        assert diagnostic.compte_claude() is not None
