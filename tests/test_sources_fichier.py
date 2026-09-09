"""Le registre des sources dans un fichier, et les jetons hors de ce fichier."""

from pathlib import Path

import pytest

from greffier.adaptateurs import sources_fichier
from greffier.domaine.sources import Droit, Genre, Source


@pytest.fixture
def fichier(tmp_path: Path) -> Path:
    return tmp_path / "sources.toml"


def ecrire(fichier: Path, contenu: str) -> Path:
    fichier.write_text(contenu, encoding="utf-8")
    return fichier


class TestGabarit:
    def test_le_gabarit_est_pose_quand_le_fichier_manque(self, fichier):
        assert sources_fichier.poser_le_gabarit(fichier)
        assert fichier.exists()

    def test_il_n_ecrase_jamais_un_fichier_existant(self, fichier):
        """Le registre est écrit à la main : l'écraser perdrait des accès."""
        ecrire(fichier, "# le mien\n")
        assert not sources_fichier.poser_le_gabarit(fichier)
        assert fichier.read_text(encoding="utf-8") == "# le mien\n"

    def test_le_gabarit_ne_declare_aucune_source(self, fichier):
        """Rien n'est atteignable avant qu'un humain l'inscrive."""
        sources_fichier.poser_le_gabarit(fichier)
        assert sources_fichier.lire(fichier).sources == []

    def test_le_gabarit_dit_ou_mettre_le_jeton_pas_le_jeton(self, fichier):
        sources_fichier.poser_le_gabarit(fichier)
        dit = fichier.read_text(encoding="utf-8")
        assert "trousseau:" in dit
        assert "security add-generic-password" in dit


class TestLecture:
    def test_un_fichier_absent_ne_donne_aucune_source(self, fichier):
        assert sources_fichier.lire(fichier).sources == []

    def test_un_fichier_illisible_ne_fait_pas_tomber(self, fichier):
        ecrire(fichier, "ceci n'est pas du TOML [[[")
        assert sources_fichier.lire(fichier).sources == []

    def test_une_source_inscrite_est_lue(self, fichier):
        ecrire(fichier, """
[[sources]]
nom = "recherche"
genre = "gitlab"
adresse = "https://gitlab.example.fr"
projet = "equipe/outil"
jeton = "GREFFIER_GITLAB_JETON"
""")
        source = sources_fichier.lire(fichier).sources[0]
        assert source.nom == "recherche"
        assert source.genre is Genre.GITLAB
        assert source.projet == "equipe/outil"

    def test_la_lecture_seule_est_le_defaut_du_fichier(self, fichier):
        ecrire(fichier, """
[[sources]]
nom = "x"
genre = "jira"
adresse = "https://x.atlassian.net"
projet = "PROJ"
""")
        assert not sources_fichier.lire(fichier).sources[0].peut_ecrire

    def test_l_ecriture_se_declare_explicitement(self, fichier):
        ecrire(fichier, """
[[sources]]
nom = "x"
genre = "jira"
adresse = "https://x.atlassian.net"
projet = "PROJ"
droit = "écriture"
""")
        assert sources_fichier.lire(fichier).sources[0].droit is Droit.ECRITURE

    def test_la_barre_finale_de_l_adresse_est_retiree(self, fichier):
        """Sinon l'appel vise « …fr//api/v4 », que GitLab refuse."""
        ecrire(fichier, """
[[sources]]
nom = "x"
genre = "gitlab"
adresse = "https://gitlab.example.fr/"
projet = "a/b"
""")
        assert sources_fichier.lire(fichier).sources[0].adresse.endswith(".fr")

    def test_une_entree_invalide_est_ecartee_sans_perdre_les_autres(self, fichier):
        ecrire(fichier, """
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
        assert sources_fichier.lire(fichier).inscrites() == ["bonne"]

    def test_un_genre_inconnu_est_ecarte(self, fichier):
        """« github » n'est pas branché : mieux vaut absent qu'à moitié.'"""
        ecrire(fichier, """
[[sources]]
nom = "x"
genre = "github"
adresse = "https://github.com"
projet = "a/b"
""")
        assert sources_fichier.lire(fichier).sources == []


class TestJeton:
    def test_une_variable_d_environnement_est_lue(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_ESSAI_JETON", "glpat-secret")
        source = Source(nom="x", genre=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", jeton="GREFFIER_ESSAI_JETON")
        assert sources_fichier.jeton_de(source) == "glpat-secret"

    def test_une_variable_absente_ne_leve_pas(self, monkeypatch):
        """Un jeton absent est un réglage à finir, pas une panne."""
        monkeypatch.delenv("GREFFIER_ABSENT", raising=False)
        source = Source(nom="x", genre=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", jeton="GREFFIER_ABSENT")
        assert sources_fichier.jeton_de(source) == ""

    def test_une_source_sans_jeton_declare_rend_rien(self):
        source = Source(nom="x", genre=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b")
        assert sources_fichier.jeton_de(source) == ""

    def test_le_trousseau_est_interroge_pour_le_prefixe(self, monkeypatch):
        appels: list[list[str]] = []

        def rendre(commande, **_options):
            appels.append(commande)
            return type("Fait", (), {"returncode": 0, "stdout": "du-trousseau\n"})()

        monkeypatch.setattr(sources_fichier.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(sources_fichier.shutil, "which", lambda _n: "/usr/bin/security")
        monkeypatch.setattr(sources_fichier.subprocess, "run", rendre)
        source = Source(nom="x", genre=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", jeton="trousseau:greffier-gitlab")
        assert sources_fichier.jeton_de(source) == "du-trousseau"
        assert "greffier-gitlab" in appels[0]

    def test_un_trousseau_qui_refuse_rend_rien(self, monkeypatch):
        monkeypatch.setattr(sources_fichier.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(sources_fichier.shutil, "which", lambda _n: "/usr/bin/security")
        monkeypatch.setattr(
            sources_fichier.subprocess, "run",
            lambda *_a, **_k: type("Fait", (), {"returncode": 44, "stdout": ""})(),
        )
        source = Source(nom="x", genre=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", jeton="trousseau:absent")
        assert sources_fichier.jeton_de(source) == ""

    def test_hors_macos_le_trousseau_n_est_pas_appele(self, monkeypatch):
        def jamais(*_a, **_k):
            raise AssertionError("security n'existe pas ici")

        monkeypatch.setattr(sources_fichier.platform, "system", lambda: "Linux")
        monkeypatch.setattr(sources_fichier.subprocess, "run", jamais)
        source = Source(nom="x", genre=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", jeton="trousseau:x")
        assert sources_fichier.jeton_de(source) == ""
