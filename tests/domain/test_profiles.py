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
    "I'm Lise and I'm the project manager.",
)


class TestLeRegistre:
    def test_le_francais_est_servi(self):
        assert profiles.pour("fr") is FRENCH

    def test_la_casse_du_code_ne_compte_pas(self):
        assert profiles.pour("FR") is FRENCH

    def test_une_langue_sans_profil_recoit_le_neutre(self):
        assert profiles.pour("en") is NEUTRAL

    def test_un_code_absent_ne_leve_jamais(self):
        """Une réunion déjà enregistrée ne doit pas se perdre sur un code
        mal saisi : mieux vaut nommer les voix à la main."""
        assert profiles.pour(None) is NEUTRAL
        assert profiles.pour("") is NEUTRAL
        assert profiles.pour("  zz  ") is NEUTRAL


class TestLeProfilNeutreNInventeRien:
    def test_aucun_participant_n_est_fabrique_en_anglais(self):
        """Avec le profil français, ces phrases rendaient « Budget »,
        « Anyway » et « Marketing » — trois participants qui n'existent pas."""
        assert spot_mentions(say(*ANGLAIS), NEUTRAL) == []

    def test_le_francais_les_fabriquait_bien(self):
        """La preuve que couper la détection est une correction, et non un
        renoncement : le défaut est reproduit ici, à demeure."""
        inventes = {m.name for m in spot_mentions(say(*ANGLAIS), FRENCH)}
        assert {"Budget", "Anyway", "Marketing"} <= inventes

    def test_le_neutre_ne_se_declare_pas_eprouve(self):
        assert not NEUTRAL.eprouve
        assert FRENCH.eprouve


class TestUnProfilEprouveRetrouveSesPrenoms:
    """La barrière qui empêche de déclarer éprouvé un profil jamais lu.

    Les trois formes de mention doivent fonctionner : celui qui se nomme, celui
    qu'on interpelle, celui à qui on renvoie.
    """

    def test_les_trois_formes_de_mention(self):
        mentions = spot_mentions(
            say(
                "Bonjour, moi c'est Jacques, on commence par la recette.",
                "Sandy, tu peux nous dire où en sont les anomalies ?",
                "Merci Sandy pour le point.",
            ),
            FRENCH,
        )
        assert {"Jacques", "Sandy"} <= {m.name for m in mentions}

    def test_tout_profil_eprouve_a_de_quoi_detecter(self):
        for profil in profiles.REGISTRE.values():
            if not profil.eprouve:
                continue
            assert profil.detection.motifs, profil.code
            assert profil.detection.exclus, profil.code


class TestDecoupage:
    def test_le_francais_compte_les_mots_par_les_espaces(self):
        assert FRENCH.decoupage.count_them("on décale la recette à jeudi") == 6

    def test_une_langue_sans_espaces_compte_ses_caracteres(self):
        """Compter les espaces rendait un ou deux sur une transcription
        chinoise valable, qui passait alors pour vide et interrompait la
        chaîne avant la rédaction."""
        assert NEUTRAL.decoupage.count_them("点検会議を始めます") > 5
