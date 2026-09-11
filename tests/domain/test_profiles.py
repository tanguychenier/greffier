"""What a language profile promises, and what the neutral one guards against.

Detecting first names was French in the code, and applied to another language
it does not fail: it invents. Measured on the real functions before this
change, with the French profile applied to ordinary English.
"""

from greffier.domain import profiles
from greffier.domain.models import Span, Utterance
from greffier.domain.names import spot_mentions
from greffier.domain.profiles.french import FRENCH
from greffier.domain.profiles.neutral import NEUTRAL


def say(*texts: str) -> list[Utterance]:
    return [
        Utterance(span=Span(i * 5.0, i * 5.0 + 4.0), text=text)
        for i, text in enumerate(texts)
    ]


#: Two ordinary English sentences on which the French patterns returned
#: "Budget" and "Anyway", and an introduction they missed.
ANGLAIS = (
    "Budget, on the other hand, is not settled.",
    "Anyway, on Monday we ship.",
    "Marketing, on our side, is ready.",
    "I'm Laura and I'm the project manager.",
)


class TestTheRegisterOfProfiles:
    def test_french_is_served(self):
        assert profiles.pour("fr") is FRENCH

    def test_the_case_of_the_code_does_not_count(self):
        assert profiles.pour("FR") is FRENCH

    def test_a_language_with_no_profile_gets_the_neutral_one(self):
        assert profiles.pour("en") is NEUTRAL

    def test_a_missing_code_never_raises(self):
        """A meeting already recorded must not be lost over a mistyped code: better to
        name the voices by hand.
        """
        assert profiles.pour(None) is NEUTRAL
        assert profiles.pour("") is NEUTRAL
        assert profiles.pour("  zz  ") is NEUTRAL


class TestTheNeutralProfileInventsNothing:
    def test_no_participant_is_manufactured_in_english(self):
        """With the French profile these sentences returned "Budget", "Anyway" and
        "Marketing" — three participants who do not exist.
        """
        assert spot_mentions(say(*ANGLAIS), NEUTRAL) == []

    def test_french_did_manufacture_them(self):
        """The proof that switching the detection off is a fix and not a retreat: the
        defect is reproduced here, for good.
        """
        inventes = {m.name for m in spot_mentions(say(*ANGLAIS), FRENCH)}
        assert {"Budget", "Anyway", "Marketing"} <= inventes

    def test_the_neutral_one_does_not_claim_to_be_tested(self):
        assert not NEUTRAL.eprouve
        assert FRENCH.eprouve


class TestATestedProfileFindsItsFirstNames:
    """The barrier that stops a profile nobody ever read being declared tested."""

    def test_the_three_forms_of_a_mention(self):
        mentions = spot_mentions(
            say(
                "Bonjour, moi c'est Jacques, on commence par la recette.",
                "Sandy, tu peux nous dire où en sont les anomalies ?",
                "Merci Sandy pour le point.",
            ),
            FRENCH,
        )
        assert {"Jacques", "Sandy"} <= {m.name for m in mentions}

    def test_every_tested_profile_has_what_it_takes(self):
        for profil in profiles.REGISTRE.values():
            if not profil.eprouve:
                continue
            assert profil.detection.motifs, profil.code
            assert profil.detection.excluded, profil.code


class TestCuttingIntoTurns:
    def test_french_counts_words_by_the_spaces(self):
        assert FRENCH.splitting.count_them("on décale la recette à jeudi") == 6

    def test_a_language_without_spaces_counts_characters(self):
        """Counting spaces returned one or two on a perfectly good Chinese transcription,
        which then passed for empty and stopped the chain before the write-up.
        """
        assert NEUTRAL.splitting.count_them("点検会議を始めます") > 5
