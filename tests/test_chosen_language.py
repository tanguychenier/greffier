"""The language becomes a choice, and that choice has to survive.

Three traps, only one of them visible.

The first: the language written into the `.env`. The order of priority is the
environment, then `.env`, then `config.toml`; a language set in the `.env` would
win for ever and make the dropdown in the Settings inert, with no error to say
so.

The second: a field missing from `SECTIONS`. The settings file is regenerated,
not patched, so a field forgotten there is lost on the first save from the
window.

The third: the writing guidance. A hundred lines of adjustments won on real
meetings — the French has to come out of it character for character.
"""

from greffier.adapters.assistant_terminal import Answers
from greffier.adapters.configuration import SECTIONS, Config, render
from greffier.adapters.writer_claude import GUIDANCE, guidance
from greffier.adapters.writer_ollama import GUIDANCE as CONSIGNES_OLLAMA
from greffier.adapters.writer_ollama import guidance as consignes_ollama
from greffier.domain.languages import LANGUAGES, eprouvee, label_text, name_of


class TestTheLanguageNeverLandsInTheEnvFile:
    def test_it_goes_into_the_settings(self):
        answers = Answers()
        answers.set_up("transcription", "langue", "de")

        assert answers.settings == {"transcription": {"langue": "de"}}

    def test_and_not_into_the_env_file(self):
        """Otherwise the dropdown in the Settings could no longer change anything."""
        answers = Answers()
        answers.set_up("transcription", "langue", "de")
        answers.set_up("compte_rendu", "langue", "fr")

        assert "LANGUE" not in answers.render_env().upper()
        assert answers.values == {}


class TestTheLanguageOfTheMinutesSurvives:
    def test_it_is_among_the_sections_written_back(self):
        """The file is regenerated: a field missing from here is lost."""
        assert "langue" in SECTIONS["compte_rendu"]

    def test_it_is_found_in_the_file_written(self):
        config = Config()
        config.minutes.language = "en"

        assert 'langue = "en"' in render(config) or "langue = 'en'" in render(config)

    def test_empty_by_default_means_the_one_of_the_meeting(self):
        assert Config().minutes.language == ""


class TestTheGuidanceFollowsTheLanguage:
    def test_french_is_unchanged_character_for_character(self):
        assert guidance("") == GUIDANCE
        assert guidance("fr") == GUIDANCE
        assert consignes_ollama("fr") == CONSIGNES_OLLAMA

    def test_another_language_is_dictated_at_the_top(self):
        assert guidance("en").startswith("Rédige entièrement en Anglais")

    def test_and_recalled_at_the_end(self):
        """A model reading a hundred lines of French happily falls back into it."""
        assert guidance("en").rstrip().endswith("le compte rendu s'écrit en Anglais.")

    def test_the_mention_of_french_disappears(self):
        assert "en français" not in guidance("de")
        assert "Allemand" in guidance("de")


class TestTheCatalogueSaysWhatEachLanguageGets:
    def test_french_is_tested(self):
        assert eprouvee("fr")

    def test_the_others_are_not_and_say_so(self):
        assert not eprouvee("en")
        assert "à nommer à la main" in label_text("en")

    def test_automatic_detection_promises_nothing_false(self):
        assert label_text("") == "Détection automatique"

    def test_no_code_appears_twice(self):
        codes = [code for code, _ in LANGUAGES]
        assert len(codes) == len(set(codes))

    def test_an_unknown_code_returns_itself(self):
        assert name_of("xx") == "xx"
