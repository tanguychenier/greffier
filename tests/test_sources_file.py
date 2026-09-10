"""Le registre des sources dans un fichier, et les jetons hors de ce fichier."""

from pathlib import Path

import pytest

from greffier.adapters import sources_file
from greffier.domain.sources import Droit, Genre, Source


@pytest.fixture
def file(tmp_path: Path) -> Path:
    return tmp_path / "sources.toml"


def write(file: Path, content: str) -> Path:
    file.write_text(content, encoding="utf-8")
    return file


class TestGabarit:
    def test_le_gabarit_est_pose_quand_le_fichier_manque(self, file):
        assert sources_file.lay_the_template(file)
        assert file.exists()

    def test_il_n_ecrase_jamais_un_fichier_existant(self, file):
        """Le registre est écrit à la main : l'écraser perdrait des accès."""
        write(file, "# le mien\n")
        assert not sources_file.lay_the_template(file)
        assert file.read_text(encoding="utf-8") == "# le mien\n"

    def test_le_gabarit_ne_declare_aucune_source(self, file):
        """Rien n'est atteignable avant qu'un humain l'inscrive."""
        sources_file.lay_the_template(file)
        assert sources_file.read(file).sources == []

    def test_le_gabarit_dit_ou_mettre_le_jeton_pas_le_jeton(self, file):
        sources_file.lay_the_template(file)
        dit = file.read_text(encoding="utf-8")
        assert "trousseau:" in dit
        assert "security add-generic-password" in dit


class TestLecture:
    def test_un_fichier_absent_ne_donne_aucune_source(self, file):
        assert sources_file.read(file).sources == []

    def test_un_fichier_illisible_ne_fait_pas_tomber(self, file):
        write(file, "ceci n'est pas du TOML [[[")
        assert sources_file.read(file).sources == []

    def test_une_source_inscrite_est_lue(self, file):
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
        assert source.kind is Genre.GITLAB
        assert source.projet == "equipe/outil"

    def test_la_lecture_seule_est_le_defaut_du_fichier(self, file):
        write(file, """
[[sources]]
nom = "x"
genre = "jira"
adresse = "https://x.atlassian.net"
projet = "PROJ"
""")
        assert not sources_file.read(file).sources[0].can_write

    def test_l_ecriture_se_declare_explicitement(self, file):
        write(file, """
[[sources]]
nom = "x"
genre = "jira"
adresse = "https://x.atlassian.net"
projet = "PROJ"
droit = "écriture"
""")
        assert sources_file.read(file).sources[0].droit is Droit.ECRITURE

    def test_la_barre_finale_de_l_adresse_est_retiree(self, file):
        """Sinon l'appel vise « …fr//api/v4 », que GitLab refuse."""
        write(file, """
[[sources]]
nom = "x"
genre = "gitlab"
adresse = "https://gitlab.example.fr/"
projet = "a/b"
""")
        assert sources_file.read(file).sources[0].adresse.endswith(".fr")

    def test_une_entree_invalide_est_ecartee_sans_perdre_les_autres(self, file):
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

    def test_un_genre_inconnu_est_ecarte(self, file):
        """« github » n'est pas branché : mieux vaut absent qu'à moitié.'"""
        write(file, """
[[sources]]
nom = "x"
genre = "github"
adresse = "https://github.com"
projet = "a/b"
""")
        assert sources_file.read(file).sources == []


class TestJeton:
    def test_une_variable_d_environnement_est_lue(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_ESSAI_JETON", "glpat-secret")
        source = Source(name="x", kind=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", token="GREFFIER_ESSAI_JETON")
        assert sources_file.token_for(source) == "glpat-secret"

    def test_une_variable_absente_ne_leve_pas(self, monkeypatch):
        """Un jeton absent est un réglage à finir, pas une panne."""
        monkeypatch.delenv("GREFFIER_ABSENT", raising=False)
        source = Source(name="x", kind=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", token="GREFFIER_ABSENT")
        assert sources_file.token_for(source) == ""

    def test_une_source_sans_jeton_declare_rend_rien(self):
        source = Source(name="x", kind=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b")
        assert sources_file.token_for(source) == ""

    def test_le_trousseau_est_interroge_pour_le_prefixe(self, monkeypatch):
        appels: list[list[str]] = []

        def render(command, **_options):
            appels.append(command)
            return type("Fait", (), {"returncode": 0, "stdout": "du-trousseau\n"})()

        monkeypatch.setattr(sources_file.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(sources_file.shutil, "which", lambda _n: "/usr/bin/security")
        monkeypatch.setattr(sources_file.subprocess, "run", render)
        source = Source(name="x", kind=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", token="trousseau:greffier-gitlab")
        assert sources_file.token_for(source) == "du-trousseau"
        assert "greffier-gitlab" in appels[0]

    def test_un_trousseau_qui_refuse_rend_rien(self, monkeypatch):
        monkeypatch.setattr(sources_file.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(sources_file.shutil, "which", lambda _n: "/usr/bin/security")
        monkeypatch.setattr(
            sources_file.subprocess, "run",
            lambda *_a, **_k: type("Fait", (), {"returncode": 44, "stdout": ""})(),
        )
        source = Source(name="x", kind=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", token="trousseau:absent")
        assert sources_file.token_for(source) == ""

    def test_hors_macos_le_trousseau_n_est_pas_appele(self, monkeypatch):
        def jamais(*_a, **_k):
            raise AssertionError("security n'existe pas ici")

        monkeypatch.setattr(sources_file.platform, "system", lambda: "Linux")
        monkeypatch.setattr(sources_file.subprocess, "run", jamais)
        source = Source(name="x", kind=Genre.GITLAB, adresse="https://x.fr",
                        projet="a/b", token="trousseau:x")
        assert sources_file.token_for(source) == ""
