"""The languages the tool accepts, and what it promises in each.

The dropdown of the settings is built from this catalogue, and what it shows
next to a language is a promise: first names are recognised in French and in
no other language yet. A label that kept quiet about it would send someone
into a meeting expecting names that never come.
"""

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.languages import LANGUAGES, label_text, name_of, proven

CODES = [code for code, _ in LANGUAGES]

#: A code the catalogue has never heard of: two to three ASCII letters, as
#: a hand-typed `langue = "xx"` in the settings file would be.
unknown_codes = st.text(string.ascii_lowercase, min_size=2, max_size=3).filter(
    lambda code: code not in CODES
)


class TestTheNameOfALanguage:
    def test_a_language_is_named_in_french(self):
        """The window is French: « Anglais », not « English »."""
        assert name_of("fr") == "Français"
        assert name_of("en") == "Anglais"

    @pytest.mark.parametrize(("code", "name"), LANGUAGES, ids=[c or "auto" for c in CODES])
    def test_every_language_of_the_catalogue_has_its_name(self, code, name):
        assert name_of(code) == name

    def test_leaving_the_language_to_the_model_has_a_name_too(self):
        assert name_of("") == "Détection automatique"

    @given(unknown_codes)
    def test_an_unknown_code_is_shown_as_it_is(self, code):
        """Better a bare « xx » in the dropdown than a crash or another language."""
        assert name_of(code) == code


class TestWhatIsProven:
    def test_french_is(self):
        assert proven("fr")

    @pytest.mark.parametrize("code", [code for code in CODES if code not in ("fr", "")])
    def test_no_other_language_of_the_catalogue_claims_it(self, code):
        """Measured before the profiles existed: the French patterns applied to
        English invented participants named « Budget » and « Anyway »."""
        assert not proven(code)

    def test_the_case_of_the_code_does_not_count(self):
        """A settings file typed by hand says « FR » as often as « fr »."""
        assert proven("FR")

    @given(unknown_codes)
    def test_nothing_is_promised_in_a_language_nobody_declared(self, code):
        assert not proven(code)


class TestTheLabelNextToALanguage:
    def test_french_is_shown_plain(self):
        assert label_text("fr") == "Français"

    def test_automatic_detection_promises_nothing_false(self):
        """It is not a language, so it has nothing to warn about."""
        assert label_text("") == "Détection automatique"

    def test_an_unproven_language_says_what_it_does_not_do(self):
        assert label_text("en") == "Anglais : voix à nommer à la main"

    @pytest.mark.parametrize("code", CODES, ids=[c or "auto" for c in CODES])
    def test_the_label_begins_with_the_name(self, code):
        assert label_text(code).startswith(name_of(code))

    @pytest.mark.parametrize("code", CODES, ids=[c or "auto" for c in CODES])
    def test_the_warning_goes_exactly_where_names_are_not_recognised(self, code):
        warned = label_text(code) != name_of(code)
        assert warned == (code not in ("fr", ""))
        if warned:
            assert label_text(code).endswith(" : voix à nommer à la main")

    @given(unknown_codes)
    def test_an_unknown_language_is_warned_about_as_well(self, code):
        assert label_text(code) == f"{code} : voix à nommer à la main"

    def test_no_two_entries_of_the_dropdown_read_the_same(self):
        labels = [label_text(code) for code in CODES]
        assert len(set(labels)) == len(labels)
