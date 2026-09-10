"""Ce que l'outil a le droit de consulter, et d'écrire."""

import pytest

from greffier.domain.sources import Droit, Genre, Registre, Source


def gitlab(name: str = "recherche", droit: Droit = Droit.LECTURE) -> Source:
    return Source(
        name=name, kind=Genre.GITLAB, adresse="https://gitlab.example.fr",
        projet="equipe/outil", droit=droit, token="GREFFIER_GITLAB_JETON",
    )


class TestSourceImpossible:
    def test_une_source_sans_nom_est_refusee(self):
        with pytest.raises(ValueError, match="sans nom"):
            Source(name=" ", kind=Genre.GITLAB,
                   adresse="https://x.fr", projet="a/b")

    def test_une_source_sans_projet_est_refusee(self):
        """Autoriser « tout GitLab » ne bornerait rien."""
        with pytest.raises(ValueError, match="sans projet"):
            Source(name="x", kind=Genre.GITLAB,
                   adresse="https://x.fr", projet="  ")

    def test_une_adresse_qui_n_en_est_pas_une_est_refusee(self):
        with pytest.raises(ValueError, match="adresse"):
            Source(name="x", kind=Genre.GITLAB, adresse="gitlab.example.fr",
                   projet="a/b")


class TestDroits:
    def test_la_lecture_seule_est_le_defaut(self):
        """Le cas qui rend service sans rien risquer."""
        assert gitlab().droit is Droit.LECTURE
        assert not gitlab().can_write

    def test_l_ecriture_se_donne_source_par_source(self):
        assert gitlab(droit=Droit.ECRITURE).can_write


class TestAutorisation:
    def test_une_source_inconnue_est_refusee(self):
        """Découvrir un projet et s'y mettre n'arrive jamais."""
        registre = Registre([gitlab()])
        permis, because = registre.allowed("autre-chose", ecriture=False)
        assert not permis
        assert "n'est pas inscrite" in because

    def test_le_refus_dit_ce_qui_est_connu(self):
        """Un « non » sans raison laisse croire à une panne."""
        _, because = Registre([gitlab("recherche")]).allowed("x", ecriture=False)
        assert "recherche" in because

    def test_lire_une_source_en_lecture_est_permis(self):
        permis, _ = Registre([gitlab()]).allowed("recherche", ecriture=False)
        assert permis

    def test_ecrire_sur_une_source_en_lecture_est_refuse(self):
        permis, because = Registre([gitlab()]).allowed("recherche", ecriture=True)
        assert not permis
        assert "lecture seule" in because

    def test_ecrire_sur_une_source_autorisee_est_permis(self):
        registre = Registre([gitlab(droit=Droit.ECRITURE)])
        permis, _ = registre.allowed("recherche", ecriture=True)
        assert permis

    def test_une_source_sans_jeton_est_refusee(self):
        sans = Source(name="x", kind=Genre.JIRA, adresse="https://x.fr",
                      projet="PROJ", token="")
        permis, because = Registre([sans]).allowed("x", ecriture=False)
        assert not permis
        assert "jeton" in because


class TestLeJetonNeVitPasIci:
    def test_le_registre_ne_porte_qu_un_nom_de_variable(self):
        """Un secret dans un fichier de configuration finit dans une sauvegarde."""
        assert gitlab().token == "GREFFIER_GITLAB_JETON"
        assert "glpat" not in gitlab().token


class TestLecture:
    def test_les_sources_se_retrouvent_par_nom(self):
        assert Registre([gitlab()]).by_name("RECHERCHE") is not None

    def test_elles_se_filtrent_par_genre(self):
        registre = Registre([gitlab()])
        assert registre.of_gender(Genre.GITLAB)
        assert registre.of_gender(Genre.JIRA) == []

    def test_la_portee_reelle_est_affichable(self):
        phrase = gitlab().say()
        assert "equipe/outil" in phrase and "lecture" in phrase
