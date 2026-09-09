"""Ce que l'outil a le droit de consulter, et d'écrire."""

import pytest

from greffier.domaine.sources import Droit, Genre, Registre, Source


def gitlab(nom: str = "recherche", droit: Droit = Droit.LECTURE) -> Source:
    return Source(
        nom=nom, genre=Genre.GITLAB, adresse="https://gitlab.example.fr",
        projet="equipe/outil", droit=droit, jeton="GREFFIER_GITLAB_JETON",
    )


class TestSourceImpossible:
    def test_une_source_sans_nom_est_refusee(self):
        with pytest.raises(ValueError, match="sans nom"):
            Source(nom=" ", genre=Genre.GITLAB,
                   adresse="https://x.fr", projet="a/b")

    def test_une_source_sans_projet_est_refusee(self):
        """Autoriser « tout GitLab » ne bornerait rien."""
        with pytest.raises(ValueError, match="sans projet"):
            Source(nom="x", genre=Genre.GITLAB,
                   adresse="https://x.fr", projet="  ")

    def test_une_adresse_qui_n_en_est_pas_une_est_refusee(self):
        with pytest.raises(ValueError, match="adresse"):
            Source(nom="x", genre=Genre.GITLAB, adresse="gitlab.example.fr",
                   projet="a/b")


class TestDroits:
    def test_la_lecture_seule_est_le_defaut(self):
        """Le cas qui rend service sans rien risquer."""
        assert gitlab().droit is Droit.LECTURE
        assert not gitlab().peut_ecrire

    def test_l_ecriture_se_donne_source_par_source(self):
        assert gitlab(droit=Droit.ECRITURE).peut_ecrire


class TestAutorisation:
    def test_une_source_inconnue_est_refusee(self):
        """Découvrir un projet et s'y mettre n'arrive jamais."""
        registre = Registre([gitlab()])
        permis, raison = registre.autorise("autre-chose", ecriture=False)
        assert not permis
        assert "n'est pas inscrite" in raison

    def test_le_refus_dit_ce_qui_est_connu(self):
        """Un « non » sans raison laisse croire à une panne."""
        _, raison = Registre([gitlab("recherche")]).autorise("x", ecriture=False)
        assert "recherche" in raison

    def test_lire_une_source_en_lecture_est_permis(self):
        permis, _ = Registre([gitlab()]).autorise("recherche", ecriture=False)
        assert permis

    def test_ecrire_sur_une_source_en_lecture_est_refuse(self):
        permis, raison = Registre([gitlab()]).autorise("recherche", ecriture=True)
        assert not permis
        assert "lecture seule" in raison

    def test_ecrire_sur_une_source_autorisee_est_permis(self):
        registre = Registre([gitlab(droit=Droit.ECRITURE)])
        permis, _ = registre.autorise("recherche", ecriture=True)
        assert permis

    def test_une_source_sans_jeton_est_refusee(self):
        sans = Source(nom="x", genre=Genre.JIRA, adresse="https://x.fr",
                      projet="PROJ", jeton="")
        permis, raison = Registre([sans]).autorise("x", ecriture=False)
        assert not permis
        assert "jeton" in raison


class TestLeJetonNeVitPasIci:
    def test_le_registre_ne_porte_qu_un_nom_de_variable(self):
        """Un secret dans un fichier de configuration finit dans une sauvegarde."""
        assert gitlab().jeton == "GREFFIER_GITLAB_JETON"
        assert "glpat" not in gitlab().jeton


class TestLecture:
    def test_les_sources_se_retrouvent_par_nom(self):
        assert Registre([gitlab()]).par_nom("RECHERCHE") is not None

    def test_elles_se_filtrent_par_genre(self):
        registre = Registre([gitlab()])
        assert registre.du_genre(Genre.GITLAB)
        assert registre.du_genre(Genre.JIRA) == []

    def test_la_portee_reelle_est_affichable(self):
        phrase = gitlab().dire()
        assert "equipe/outil" in phrase and "lecture" in phrase
