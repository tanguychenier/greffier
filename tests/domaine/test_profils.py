"""Ce qu'un profil de langue promet, et ce que le profil neutre protège.

La détection des prénoms était française en dur, et appliquée à une autre langue
elle n'échoue pas : elle invente. Mesuré sur les vraies fonctions avant ce
changement, avec le profil français appliqué à de l'anglais ordinaire.
"""

from greffier.domaine import profils
from greffier.domaine.modeles import Intervalle, Replique
from greffier.domaine.noms import reperer_mentions
from greffier.domaine.profils.francais import FRANCAIS
from greffier.domaine.profils.neutre import NEUTRE


def dire(*textes: str) -> list[Replique]:
    return [
        Replique(intervalle=Intervalle(i * 5.0, i * 5.0 + 4.0), texte=texte)
        for i, texte in enumerate(textes)
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
        assert profils.pour("fr") is FRANCAIS

    def test_la_casse_du_code_ne_compte_pas(self):
        assert profils.pour("FR") is FRANCAIS

    def test_une_langue_sans_profil_recoit_le_neutre(self):
        assert profils.pour("en") is NEUTRE

    def test_un_code_absent_ne_leve_jamais(self):
        """Une réunion déjà enregistrée ne doit pas se perdre sur un code
        mal saisi : mieux vaut nommer les voix à la main."""
        assert profils.pour(None) is NEUTRE
        assert profils.pour("") is NEUTRE
        assert profils.pour("  zz  ") is NEUTRE


class TestLeProfilNeutreNInventeRien:
    def test_aucun_participant_n_est_fabrique_en_anglais(self):
        """Avec le profil français, ces phrases rendaient « Budget »,
        « Anyway » et « Marketing » — trois participants qui n'existent pas."""
        assert reperer_mentions(dire(*ANGLAIS), NEUTRE) == []

    def test_le_francais_les_fabriquait_bien(self):
        """La preuve que couper la détection est une correction, et non un
        renoncement : le défaut est reproduit ici, à demeure."""
        inventes = {m.nom for m in reperer_mentions(dire(*ANGLAIS), FRANCAIS)}
        assert {"Budget", "Anyway", "Marketing"} <= inventes

    def test_le_neutre_ne_se_declare_pas_eprouve(self):
        assert not NEUTRE.eprouve
        assert FRANCAIS.eprouve


class TestUnProfilEprouveRetrouveSesPrenoms:
    """La barrière qui empêche de déclarer éprouvé un profil jamais lu.

    Les trois formes de mention doivent fonctionner : celui qui se nomme, celui
    qu'on interpelle, celui à qui on renvoie.
    """

    def test_les_trois_formes_de_mention(self):
        mentions = reperer_mentions(
            dire(
                "Bonjour, moi c'est Jacques, on commence par la recette.",
                "Sandy, tu peux nous dire où en sont les anomalies ?",
                "Merci Sandy pour le point.",
            ),
            FRANCAIS,
        )
        assert {"Jacques", "Sandy"} <= {m.nom for m in mentions}

    def test_tout_profil_eprouve_a_de_quoi_detecter(self):
        for profil in profils.REGISTRE.values():
            if not profil.eprouve:
                continue
            assert profil.detection.motifs, profil.code
            assert profil.detection.exclus, profil.code


class TestDecoupage:
    def test_le_francais_compte_les_mots_par_les_espaces(self):
        assert FRANCAIS.decoupage.compter("on décale la recette à jeudi") == 6

    def test_une_langue_sans_espaces_compte_ses_caracteres(self):
        """Compter les espaces rendait un ou deux sur une transcription
        chinoise valable, qui passait alors pour vide et interrompait la
        chaîne avant la rédaction."""
        assert NEUTRE.decoupage.compter("点検会議を始めます") > 5
