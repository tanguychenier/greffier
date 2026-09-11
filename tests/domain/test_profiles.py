"""Ce qu'un profil de langue promet, et ce que le profil neutre protège.

La détection des prénoms était française en dur, et appliquée à une autre langue
elle n'échoue pas : elle invente. Mesuré sur les vraies fonctions avant ce
changement, avec le profil français appliqué à de l'anglais ordinaire.
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


#: Deux phrases anglaises ordinaires sur lesquelles les motifs français
#: rendaient « Budget » et « Anyway », et une présentation qu'ils manquaient.
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
        """Une réunion déjà enregistrée ne doit pas se perdre sur un code
        mal saisi : mieux vaut nommer les voix à la main."""
        assert profiles.pour(None) is NEUTRAL
        assert profiles.pour("") is NEUTRAL
        assert profiles.pour("  zz  ") is NEUTRAL


class TestTheNeutralProfileInventsNothing:
    def test_no_participant_is_manufactured_in_english(self):
        """Avec le profil français, ces phrases rendaient « Budget »,
        « Anyway » et « Marketing » — trois participants qui n'existent pas."""
        assert spot_mentions(say(*ANGLAIS), NEUTRAL) == []

    def test_french_did_manufacture_them(self):
        """La preuve que couper la détection est une correction, et non un
        renoncement : le défaut est reproduit ici, à demeure."""
        inventes = {m.name for m in spot_mentions(say(*ANGLAIS), FRENCH)}
        assert {"Budget", "Anyway", "Marketing"} <= inventes

    def test_the_neutral_one_does_not_claim_to_be_tested(self):
        assert not NEUTRAL.eprouve
        assert FRENCH.eprouve


class TestATestedProfileFindsItsFirstNames:
    """La barrière qui empêche de déclarer éprouvé un profil jamais lu.

    Les trois formes de mention doivent fonctionner : celui qui se nomme, celui
    qu'on interpelle, celui à qui on renvoie.
    """

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
        """Compter les espaces rendait un ou deux sur une transcription
        chinoise valable, qui passait alors pour vide et interrompait la
        chaîne avant la rédaction."""
        assert NEUTRAL.splitting.count_them("点検会議を始めます") > 5
