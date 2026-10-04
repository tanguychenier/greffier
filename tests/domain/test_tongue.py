"""The language the tool speaks to the person using it.

Not the language of the meeting: a French team holds meetings in English often
enough. This is the language of the window, of the installer's messages, of what
the tool says about itself.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.tongue import FALLBACK, SPOKEN, Wording, choose, voice_for

#: What a machine wraps around the language itself: a region or none, an
#: encoding or none, either separator, any case.
regions = st.sampled_from(["", "_FR", "_CA", "-BE", "_us", "-gb"])
encodings = st.sampled_from(["", ".UTF-8", ".utf8", ".ISO8859-1"])
cases = st.sampled_from([str.lower, str.upper, str.title])
#: Two letters of a language the tool does not speak.
other_codes = st.sampled_from(["de", "ja", "es", "it", "pt", "zz"])


def as_a_machine_says_it(code: str, region: str, encoding: str,
                         case: Callable[[str], str]) -> str:
    return case(f"{code}{region}{encoding}")


class TestWhichLanguageToSpeak:
    @pytest.mark.parametrize("said", ["fr", "fr_FR", "fr_FR.UTF-8", "fr-CA", "FR"])
    def test_a_french_machine_is_answered_in_french(self, said):
        """Québécois and Belgian French read the same window: the region goes."""
        assert choose(said) == "fr"

    @pytest.mark.parametrize("said", ["en_GB.UTF-8", "en_US", "en"])
    def test_an_english_one_in_english(self, said):
        assert choose(said) == "en"

    def test_an_encoding_without_a_region_goes_as_well(self):
        """`LANG=fr.UTF-8` is rare but legal, and must not read as unknown."""
        assert choose("fr.UTF-8") == "fr"

    @pytest.mark.parametrize("said", ["de_DE.UTF-8", "ja_JP", "C", "POSIX", "", "  "])
    def test_anything_else_falls_back_to_english_not_to_french(self, said):
        """A French window is unreadable to somebody who did not ask for it."""
        assert choose(said) == "en" == FALLBACK

    @given(st.sampled_from(SPOKEN), regions, encodings, cases)
    def test_neither_region_nor_encoding_nor_case_changes_the_answer(
            self, code, region, encoding, case):
        assert choose(as_a_machine_says_it(code, region, encoding, case)) == code

    @given(other_codes, regions, encodings, cases)
    def test_a_language_not_spoken_falls_back_however_it_is_dressed(
            self, code, region, encoding, case):
        assert choose(as_a_machine_says_it(code, region, encoding, case)) == FALLBACK

    def test_the_languages_spoken_are_declared(self):
        assert "fr" in SPOKEN and FALLBACK in SPOKEN


class TestWhenEnglishIsNotSpoken:
    """English is the fallback for being spoken, not by decree: a build
    translated into French and Italian only must still answer somebody."""

    def test_the_first_language_spoken_takes_its_place(self):
        assert choose("de", spoken=("fr", "it")) == "fr"

    def test_what_is_asked_for_still_wins_when_spoken(self):
        assert choose("it_IT.UTF-8", spoken=("fr", "it")) == "it"

    def test_a_tool_that_speaks_nothing_still_answers_in_english(self):
        """Rather than fall over an empty table before the first window."""
        assert choose("de", spoken=()) == FALLBACK


class TestWhatTheToolSays:
    def _wording(self, says=None, default=None) -> Wording:
        return Wording("fr", says or {}, default or {"bonjour": "Hello", "adieu": "Bye"})

    def test_a_translated_sentence_is_used(self):
        assert self._wording({"bonjour": "Bonjour"}).say("bonjour") == "Bonjour"

    def test_a_missing_one_falls_back_rather_than_showing_the_key(self):
        """A half-translated language must read as a language, not a bug report."""
        assert self._wording({"bonjour": "Bonjour"}).say("adieu") == "Bye"

    def test_a_key_nobody_wrote_shows_itself_rather_than_raising(self):
        assert self._wording().say("nulle.part") == "nulle.part"

    def test_the_holes_are_filled(self):
        said = Wording("fr", {"salut": "Bonjour {who}"}, {})
        assert said.say("salut", who="Sophie") == "Bonjour Sophie"

    def test_a_wording_whose_holes_do_not_match_shows_the_sentence(self):
        """A translation mistake must not raise in the middle of a window."""
        said = Wording("fr", {"salut": "Bonjour {inconnu}"}, {})
        assert said.say("salut", who="Sophie") == "Bonjour {inconnu}"

    def test_what_is_missing_is_knowable(self):
        """So that it can be translated, rather than discovered by a reader."""
        assert self._wording({"bonjour": "Bonjour"}).missing() == ("adieu",)
        assert not self._wording({"bonjour": "B", "adieu": "A"}).missing()
        assert self._wording({"bonjour": "B", "adieu": "A"}).complete


class TestTheAssistantVoice:
    def test_each_spoken_language_has_one(self):
        """Otherwise the assistant speaks that language with another's accent."""
        for code in SPOKEN:
            assert voice_for(code) is not None, code

    def test_it_follows_the_language(self):
        assert voice_for("fr").archive != voice_for("en").archive
        assert "fr_FR" in voice_for("fr").archive
        assert "en_US" in voice_for("en").archive

    def test_a_language_with_no_voice_falls_back_with_the_window(self):
        """A German machine reads English and hears English, not French."""
        assert voice_for("de").archive == voice_for("en").archive

    def test_what_it_weighs_is_declared(self):
        """An installer that announces a download announces its size."""
        assert 10 < voice_for("fr").weight_mb < 500
