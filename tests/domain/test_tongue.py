"""The language the tool speaks to the person using it.

Not the language of the meeting: a French team holds meetings in English often
enough. This is the language of the window, of the installer's messages, of what
the tool says about itself.
"""

from __future__ import annotations

import pytest

from greffier.domain.tongue import FALLBACK, SPOKEN, Wording, choose, voice_for


class TestWhichLanguageToSpeak:
    @pytest.mark.parametrize("said", ["fr", "fr_FR", "fr_FR.UTF-8", "fr-CA", "FR"])
    def test_a_french_machine_is_answered_in_french(self, said):
        """Québécois and Belgian French read the same window: the region goes."""
        assert choose(said) == "fr"

    @pytest.mark.parametrize("said", ["en_GB.UTF-8", "en_US", "en"])
    def test_an_english_one_in_english(self, said):
        assert choose(said) == "en"

    @pytest.mark.parametrize("said", ["de_DE.UTF-8", "ja_JP", "C", "POSIX", "", "  "])
    def test_anything_else_falls_back_to_english_not_to_french(self, said):
        """A French window is unreadable to somebody who did not ask for it."""
        assert choose(said) == "en" == FALLBACK

    def test_the_languages_spoken_are_declared(self):
        assert "fr" in SPOKEN and FALLBACK in SPOKEN


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
        dit = Wording("fr", {"salut": "Bonjour {qui}"}, {})
        assert dit.say("salut", qui="Sophie") == "Bonjour Sophie"

    def test_a_wording_whose_holes_do_not_match_shows_the_sentence(self):
        """A translation mistake must not raise in the middle of a window."""
        dit = Wording("fr", {"salut": "Bonjour {inconnu}"}, {})
        assert dit.say("salut", qui="Sophie") == "Bonjour {inconnu}"

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
