"""What the tool may consult, and write to."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.sources import Kind, Registry, Right, Source


def gitlab(name: str = "recherche", right: Right = Right.READING) -> Source:
    return Source(
        name=name, kind=Kind.GITLAB, address="https://gitlab.example.fr",
        project="equipe/outil", right=right, token="GREFFIER_GITLAB_JETON",
    )


def jira(name: str = "suivi") -> Source:
    return Source(
        name=name, kind=Kind.JIRA, address="https://jira.example.fr",
        project="PROJ", token="GREFFIER_JIRA_JETON",
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

    def test_a_source_with_no_address_is_refused_before_the_address_is_read(self):
        """Blank is « sans adresse », not « pas une adresse »: the person
        forgot the line, they did not misspell it."""
        with pytest.raises(ValueError, match=r"^une source sans adresse ne sert à rien$"):
            Source(name="x", kind=Kind.GITLAB, address="  ", project="a/b")

    def test_an_address_that_is_not_one_is_refused(self):
        with pytest.raises(ValueError, match=(
            r"^« gitlab\.example\.fr » n'est pas une adresse : il faut http\(s\)://$"
        )):
            Source(name="x", kind=Kind.GITLAB, address="gitlab.example.fr",
                   project="a/b")

    def test_a_plain_http_address_is_one(self):
        """A forge inside the building has no certificate; it is reachable."""
        inside = Source(name="x", kind=Kind.GITLAB,
                        address="http://gitlab.interne", project="a/b")
        assert inside.address == "http://gitlab.interne"


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

    def test_the_refusal_lists_every_known_source_with_a_comma(self):
        the_registry = Registry([gitlab("recherche"), jira("suivi")])
        _, because = the_registry.allowed("x", spelling=False)
        assert because == "« x » n'est pas inscrite. Sources connues : recherche, suivi"

    def test_with_nothing_registered_the_refusal_says_so(self):
        """An empty list after the colon would read as a display fault."""
        _, because = Registry([]).allowed("x", spelling=False)
        assert because == "« x » n'est pas inscrite. Sources connues : aucune"

    def test_reading_a_readable_source_is_allowed(self):
        permitted, _ = Registry([gitlab()]).allowed("recherche", spelling=False)
        assert permitted

    def test_a_permitted_gesture_comes_with_nothing_to_say(self):
        """The reason is for a refusal; a « yes » has none to show."""
        assert Registry([gitlab()]).allowed("recherche", spelling=False) == (True, "")

    def test_writing_to_a_read_only_source_is_refused(self):
        permitted, because = Registry([gitlab()]).allowed("recherche", spelling=True)
        assert not permitted
        assert because == (
            "« recherche » est en lecture seule. Passe son droit à « écriture » "
            "dans le registre des sources si c'est voulu."
        )

    def test_writing_to_an_allowed_source_is_permitted(self):
        the_registry = Registry([gitlab(right=Right.WRITING)])
        permitted, _ = the_registry.allowed("recherche", spelling=True)
        assert permitted

    def test_a_source_with_no_token_is_refused(self):
        without = Source(name="x", kind=Kind.JIRA, address="https://x.fr",
                      project="PROJ", token="")
        permitted, because = Registry([without]).allowed("x", spelling=False)
        assert not permitted
        assert because == "« x » n'indique pas où trouver son jeton"


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

    def test_the_names_recorded_are_all_of_them_in_the_registry_order(self):
        """Offered to the person as they stand, so they can pick rather than guess."""
        the_registry = Registry([gitlab("recherche"), jira("suivi")])
        assert the_registry.recorded() == ["recherche", "suivi"]

    def test_the_names_recorded_can_be_asked_for_one_kind_only(self):
        the_registry = Registry([gitlab("recherche"), jira("suivi"), gitlab("outil")])
        assert the_registry.recorded(Kind.JIRA) == ["suivi"]
        assert the_registry.recorded(Kind.GITLAB) == ["recherche", "outil"]

    @given(st.lists(st.sampled_from(list(Kind))), st.sampled_from(list(Kind)))
    def test_the_names_recorded_for_a_kind_are_those_sources_in_order(self, kinds, kind):
        sources = [
            Source(name=f"source {rank}", kind=each, address="https://x.fr", project="a/b")
            for rank, each in enumerate(kinds)
        ]
        the_registry = Registry(sources)
        assert the_registry.recorded(kind) == [s.name for s in sources if s.kind is kind]
        assert the_registry.recorded() == [s.name for s in sources]

    def test_the_real_reach_can_be_shown(self):
        sentence = gitlab().say()
        assert "equipe/outil" in sentence and "lecture" in sentence
