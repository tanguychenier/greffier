"""The title of the minutes, read without knowing how they will be delivered.

The email subject, the window's list of meetings and the memory of past
meetings all want the title the writer gave, not the name of the file. The
symptom this answers: a subject line reduced to « 2026-09-09_10h05_reunion ».
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greffier.domain.minutes import title

#: mutmut 3 runs pytest twice in one process, the coverage pass then the
#: mutant, so a test method meets two `self` instances. Hypothesis fails it
#: for that alone, in 0.05 s, and the mutant dies of the health check rather
#: than of the rule.
in_one_process = settings(suppress_health_check=[HealthCheck.differing_executors])

#: The words of a title: no « # » that would make a heading, no « * » that
#: would make bold, no line break.
words = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZéèàç :,'0123456789",
    min_size=1,
    max_size=40,
)
blank_lines = st.lists(st.text(alphabet=" \t", max_size=3), max_size=4)


class TestReadingTheTitle:
    def test_the_first_heading_is_the_title(self):
        minutes = "# Compte rendu : Point Casa\n\nLe 25 août, en visioconférence."
        assert title(minutes, "défaut") == "Compte rendu : Point Casa"

    def test_blank_lines_before_the_heading_are_skipped(self):
        assert title("\n   \n# Point Casa\n", "défaut") == "Point Casa"

    def test_the_spaces_around_the_heading_do_not_count(self):
        assert title("   #   Point Casa   ", "défaut") == "Point Casa"

    def test_the_bold_marks_are_removed_and_the_words_kept(self):
        assert title("# Compte rendu **Casa**", "défaut") == "Compte rendu Casa"
        assert title("# **Point** sur **Casa**", "défaut") == "Point sur Casa"

    def test_a_lower_level_heading_is_not_the_title(self):
        assert title("## Décisions\n# Point Casa", "défaut") == "défaut"

    def test_a_paragraph_before_the_heading_hides_it(self):
        """The title names the document, so it comes first: a heading found
        after a paragraph is a section, whatever its level."""
        assert title("Préambule.\n# Point Casa", "défaut") == "défaut"

    def test_an_empty_heading_falls_back_on_the_default(self):
        assert title("# \n\nLe 25 août.", "défaut") == "défaut"

    def test_without_any_heading_the_default_is_kept(self):
        assert title("Pas de titre ici.", "défaut") == "défaut"
        assert title("", "défaut") == "défaut"


class TestWhateverTheMinutesSay:
    @in_one_process
    @given(heading=words, body=st.text(max_size=60), default=words)
    def test_the_heading_comes_back_as_written(self, heading, body, default):
        assert title(f"# {heading}\n{body}", default) == (heading.strip() or default)

    @in_one_process
    @given(blanks=blank_lines, heading=words, default=words)
    def test_blank_lines_above_the_heading_change_nothing(self, blanks, heading, default):
        with_blanks = "\n".join([*blanks, f"# {heading}"])
        assert title(with_blanks, default) == title(f"# {heading}", default)

    @in_one_process
    @given(opening=words, rest=st.text(max_size=60), default=words)
    def test_a_document_opening_with_prose_keeps_the_default(self, opening, rest, default):
        assert title(f"{opening}\n{rest}", default) == default
