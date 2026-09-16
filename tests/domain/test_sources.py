"""Ce que l'outil a le droit de consulter, et d'écrire."""

import pytest

from greffier.domain.sources import Kind, Registry, Right, Source


def gitlab(name: str = "recherche", droit: Right = Right.READING) -> Source:
    return Source(
        name=name, kind=Kind.GITLAB, adresse="https://gitlab.example.fr",
        project="equipe/outil", droit=droit, token="GREFFIER_GITLAB_JETON",
    )


class TestASourceThatCannotBe:
    def test_a_source_with_no_name_is_refused(self):
        with pytest.raises(ValueError, match="sans nom"):
            Source(name=" ", kind=Kind.GITLAB,
                   adresse="https://x.fr", project="a/b")

    def test_a_source_with_no_project_is_refused(self):
        """Allowing « all of GitLab » would bound nothing."""
        with pytest.raises(ValueError, match="sans projet"):
            Source(name="x", kind=Kind.GITLAB,
                   adresse="https://x.fr", project="  ")

    def test_an_address_that_is_not_one_is_refused(self):
        with pytest.raises(ValueError, match="adresse"):
            Source(name="x", kind=Kind.GITLAB, adresse="gitlab.example.fr",
                   project="a/b")


class TestRights:
    def test_read_only_is_the_default(self):
        """The case that helps without risking anything."""
        assert gitlab().droit is Right.READING
        assert not gitlab().can_write

    def test_writing_is_granted_source_by_source(self):
        assert gitlab(droit=Right.ECRITURE).can_write


class TestWhatIsAllowed:
    def test_an_unknown_source_is_refused(self):
        """Découvrir un projet et s'y mettre n'arrive jamais."""
        registre = Registry([gitlab()])
        permis, because = registre.allowed("autre-chose", ecriture=False)
        assert not permis
        assert "n'est pas inscrite" in because

    def test_the_refusal_says_what_is_known(self):
        """A « no » without a reason looks like a breakdown."""
        _, because = Registry([gitlab("recherche")]).allowed("x", ecriture=False)
        assert "recherche" in because

    def test_reading_a_readable_source_is_allowed(self):
        permis, _ = Registry([gitlab()]).allowed("recherche", ecriture=False)
        assert permis

    def test_writing_to_a_read_only_source_is_refused(self):
        permis, because = Registry([gitlab()]).allowed("recherche", ecriture=True)
        assert not permis
        assert "lecture seule" in because

    def test_writing_to_an_allowed_source_is_permitted(self):
        registre = Registry([gitlab(droit=Right.ECRITURE)])
        permis, _ = registre.allowed("recherche", ecriture=True)
        assert permis

    def test_a_source_with_no_token_is_refused(self):
        without = Source(name="x", kind=Kind.JIRA, adresse="https://x.fr",
                      project="PROJ", token="")
        permis, because = Registry([without]).allowed("x", ecriture=False)
        assert not permis
        assert "jeton" in because


class TestTheTokenDoesNotLiveHere:
    def test_the_register_carries_only_a_variable_name(self):
        """A secret in a configuration file ends up in a backup."""
        assert gitlab().token == "GREFFIER_GITLAB_JETON"
        assert "glpat" not in gitlab().token


class TestReadingTheSources:
    def test_sources_are_found_by_name(self):
        assert Registry([gitlab()]).by_name("RECHERCHE") is not None

    def test_they_filter_by_kind(self):
        registre = Registry([gitlab()])
        assert registre.of_gender(Kind.GITLAB)
        assert registre.of_gender(Kind.JIRA) == []

    def test_the_real_reach_can_be_shown(self):
        sentence = gitlab().say()
        assert "equipe/outil" in sentence and "lecture" in sentence
