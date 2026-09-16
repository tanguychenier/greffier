"""Ce que l'outil a le droit de consulter, et d'écrire."""

import pytest

from greffier.domain.sources import Kind, Registry, Right, Source


def gitlab(name: str = "recherche", right: Right = Right.READING) -> Source:
    return Source(
        name=name, kind=Kind.GITLAB, address="https://gitlab.example.fr",
        project="equipe/outil", right=right, token="GREFFIER_GITLAB_JETON",
    )


class TestASourceThatCannotBe:
    def test_a_source_with_no_name_is_refused(self):
        with pytest.raises(ValueError, match="sans nom"):
            Source(name=" ", kind=Kind.GITLAB,
                   address="https://x.fr", project="a/b")

    def test_a_source_with_no_project_is_refused(self):
        """Allowing « all of GitLab » would bound nothing."""
        with pytest.raises(ValueError, match="sans projet"):
            Source(name="x", kind=Kind.GITLAB,
                   address="https://x.fr", project="  ")

    def test_an_address_that_is_not_one_is_refused(self):
        with pytest.raises(ValueError, match="adresse"):
            Source(name="x", kind=Kind.GITLAB, address="gitlab.example.fr",
                   project="a/b")


class TestRights:
    def test_read_only_is_the_default(self):
        """The case that helps without risking anything."""
        assert gitlab().right is Right.READING
        assert not gitlab().can_write

    def test_writing_is_granted_source_by_source(self):
        assert gitlab(right=Right.WRITING).can_write


class TestWhatIsAllowed:
    def test_an_unknown_source_is_refused(self):
        """Découvrir un projet et s'y mettre n'arrive jamais."""
        the_registry = Registry([gitlab()])
        permitted, because = the_registry.allowed("autre-chose", spelling=False)
        assert not permitted
        assert "n'est pas inscrite" in because

    def test_the_refusal_says_what_is_known(self):
        """A « no » without a reason looks like a breakdown."""
        _, because = Registry([gitlab("recherche")]).allowed("x", spelling=False)
        assert "recherche" in because

    def test_reading_a_readable_source_is_allowed(self):
        permitted, _ = Registry([gitlab()]).allowed("recherche", spelling=False)
        assert permitted

    def test_writing_to_a_read_only_source_is_refused(self):
        permitted, because = Registry([gitlab()]).allowed("recherche", spelling=True)
        assert not permitted
        assert "lecture seule" in because

    def test_writing_to_an_allowed_source_is_permitted(self):
        the_registry = Registry([gitlab(right=Right.WRITING)])
        permitted, _ = the_registry.allowed("recherche", spelling=True)
        assert permitted

    def test_a_source_with_no_token_is_refused(self):
        without = Source(name="x", kind=Kind.JIRA, address="https://x.fr",
                      project="PROJ", token="")
        permitted, because = Registry([without]).allowed("x", spelling=False)
        assert not permitted
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
        the_registry = Registry([gitlab()])
        assert the_registry.of_gender(Kind.GITLAB)
        assert the_registry.of_gender(Kind.JIRA) == []

    def test_the_real_reach_can_be_shown(self):
        sentence = gitlab().say()
        assert "equipe/outil" in sentence and "lecture" in sentence
