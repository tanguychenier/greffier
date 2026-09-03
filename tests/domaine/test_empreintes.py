"""Le rapprochement des voix, sur des vecteurs écrits à la main."""

import math

import pytest

from greffier.domaine.empreintes import (
    MARGE_MINIMALE,
    MATIERE_MINIMALE_FUSION,
    SEUIL_FUSION,
    SEUIL_RECONNAISSANCE,
    agreger,
    enrichir,
    fusionner_voix,
    noms_en_conflit,
    normaliser,
    reconnaitre,
    similarite,
)
from greffier.domaine.modeles import Personne


def voix(*composantes: float, duree: float = 10.0):
    return normaliser(composantes, duree_source=duree)


class TestNormalisation:
    def test_la_norme_vaut_un(self):
        e = voix(3.0, 4.0)
        assert math.isclose(math.sqrt(sum(x * x for x in e.vecteur)), 1.0)

    def test_le_volume_ne_change_pas_l_empreinte(self):
        """Deux extraits de la même voix, l'un fort l'autre faible, restent identiques."""
        assert math.isclose(similarite(voix(1.0, 2.0, 3.0), voix(10.0, 20.0, 30.0)), 1.0)

    def test_un_extrait_sans_parole_est_refuse(self):
        with pytest.raises(ValueError, match="vecteur nul"):
            normaliser([0.0, 0.0, 0.0])

    def test_comparer_des_tailles_differentes_est_une_erreur(self):
        with pytest.raises(ValueError, match="tailles différentes"):
            similarite(voix(1.0, 0.0), voix(1.0, 0.0, 0.0))


class TestAgregation:
    def test_les_extraits_longs_pesent_davantage(self):
        """Une minute d'explication compte plus que trois secondes de « d'accord »."""
        longue = voix(1.0, 0.0, duree=60.0)
        breve = voix(0.0, 1.0, duree=3.0)
        moyenne = agreger([longue, breve])
        assert similarite(moyenne, longue) > similarite(moyenne, breve)

    def test_agreger_sans_extrait_est_une_erreur(self):
        with pytest.raises(ValueError, match="aucune empreinte"):
            agreger([])


class TestReconnaissance:
    def test_reconnait_une_voix_connue(self):
        josiane = Personne("Josiane", [voix(1.0, 0.0, 0.0)])
        marc = Personne("Marc", [voix(0.0, 1.0, 0.0)])
        trouve = reconnaitre(voix(0.95, 0.05, 0.0), [josiane, marc])
        assert trouve is not None and trouve.nom == "Josiane" and trouve.sure

    def test_une_voix_inconnue_ne_renvoie_rien(self):
        """Résultat normal et fréquent : on demandera à l'utilisateur."""
        banque = [Personne("Josiane", [voix(1.0, 0.0, 0.0)])]
        assert reconnaitre(voix(0.0, 0.0, 1.0), banque) is None

    def test_deux_voix_proches_font_hesiter(self):
        """Sans marge suffisante, mieux vaut ne rien affirmer."""
        banque = [
            Personne("Josiane", [voix(1.0, 0.02, 0.0)]),
            Personne("Jocelyne", [voix(1.0, 0.0, 0.02)]),
        ]
        assert reconnaitre(voix(1.0, 0.01, 0.01), banque) is None

    def test_une_banque_vide_ne_renvoie_rien(self):
        assert reconnaitre(voix(1.0, 0.0), []) is None
        assert reconnaitre(voix(1.0, 0.0), [Personne("Josiane", [])]) is None

    def test_on_retient_le_meilleur_extrait_pas_la_moyenne(self):
        """Enregistrée au casque puis en salle, une personne a deux signatures :
        leur moyenne ne ressemblerait à aucune des deux."""
        au_casque = voix(1.0, 0.0, 0.0)
        en_salle = voix(0.0, 1.0, 0.0)
        banque = [Personne("Josiane", [au_casque, en_salle]),
                  Personne("Marc", [voix(0.3, 0.3, 0.9)])]
        trouve = reconnaitre(voix(0.05, 0.99, 0.0), banque)
        assert trouve is not None and trouve.nom == "Josiane"

    def test_les_seuils_sont_ajustables(self):
        """Une salle réverbérante abaisse la similarité : le seuil doit suivre."""
        banque = [Personne("Josiane", [voix(1.0, 0.0, 0.0)])]
        lointaine = voix(0.5, 0.86, 0.0)
        assert reconnaitre(lointaine, banque) is None
        assert reconnaitre(lointaine, banque, seuil=0.4, marge_minimale=0.0) is not None


class TestEnrichissement:
    def test_ajoute_une_empreinte_et_compte_la_reunion(self):
        josiane = Personne("Josiane", [voix(1.0, 0.0)])
        enrichir(josiane, voix(0.9, 0.1))
        assert len(josiane.empreintes) == 2
        assert josiane.reunions == 1

    def test_l_accumulation_est_bornee_et_garde_les_extraits_longs(self):
        josiane = Personne("Josiane", [voix(1.0, 0.0, duree=float(i)) for i in range(1, 4)])
        for i in range(10):
            enrichir(josiane, voix(1.0, 0.0, duree=100.0 + i), maximum=3)
        assert len(josiane.empreintes) == 3
        assert min(e.duree_source for e in josiane.empreintes) >= 100.0

    def test_les_valeurs_par_defaut_restent_prudentes(self):
        """Documenté pour que personne ne les abaisse sans le vouloir."""
        assert SEUIL_RECONNAISSANCE >= 0.5
        assert MARGE_MINIMALE > 0


class TestFusionDesVoix:
    """La segmentation éclate une même voix : il faut la recoller."""

    def test_deux_groupes_proches_sont_reunis(self):
        par_voix = {
            "v1": [voix(1.0, 0.0, 0.0, duree=60.0)],
            "v2": [voix(0.99, 0.1, 0.0, duree=20.0)],
            "v3": [voix(0.0, 0.0, 1.0, duree=40.0)],
        }
        appartenance = fusionner_voix(par_voix)
        assert appartenance["v1"] == appartenance["v2"]
        assert appartenance["v3"] != appartenance["v1"]

    def test_le_groupe_le_plus_fourni_donne_son_nom(self):
        """L'utilisateur écoutera un extrait : autant que ce soit le plus long."""
        par_voix = {
            "court": [voix(1.0, 0.0, duree=5.0)],
            "long": [voix(0.99, 0.1, duree=120.0)],
        }
        appartenance = fusionner_voix(par_voix)
        assert appartenance["court"] == "long" and appartenance["long"] == "long"

    def test_des_voix_distinctes_ne_sont_pas_fusionnees(self):
        par_voix = {
            "v1": [voix(1.0, 0.0, 0.0)],
            "v2": [voix(0.0, 1.0, 0.0)],
            "v3": [voix(0.0, 0.0, 1.0)],
        }
        appartenance = fusionner_voix(par_voix)
        assert len(set(appartenance.values())) == 3

    def test_la_chaine_de_rapprochements_ne_derive_pas(self):
        """A proche de B, B proche de C, mais A loin de C : on ne réunit pas tout.

        L'agrégat est recalculé après chaque réunion, ce qui empêche une suite
        de petits pas de rassembler des voix qui n'ont rien à voir.
        """
        par_voix = {
            "a": [voix(1.0, 0.0, 0.0, duree=10.0)],
            "b": [voix(0.7, 0.7, 0.0, duree=10.0)],
            "c": [voix(0.0, 1.0, 0.0, duree=10.0)],
        }
        appartenance = fusionner_voix(par_voix, seuil=0.70)
        assert appartenance["a"] != appartenance["c"]

    def test_un_groupe_vide_est_ignore(self):
        par_voix = {"v1": [voix(1.0, 0.0)], "vide": []}
        appartenance = fusionner_voix(par_voix)
        assert appartenance["vide"] == "vide"

    def test_le_seuil_mesure_est_documente(self):
        """0,70 vient d'une mesure sur réunion réelle, pas d'une intuition."""
        assert SEUIL_RECONNAISSANCE == 0.70
        assert SEUIL_FUSION > SEUIL_RECONNAISSANCE

    def test_deux_petits_groupes_ne_fusionnent_pas_sur_un_accident(self):
        """Un agrégat tiré de peu de matière est bruité : la similarité seule
        ne suffit pas. Constaté sur un jeu d'essai à trois locuteurs
        synthétiques, où deux petits groupes ont franchi SEUIL_FUSION par
        accident statistique.
        """
        par_voix = {
            "v1": [voix(1.0, 0.01, duree=4.0)],
            "v2": [voix(0.99, 0.1, duree=4.0)],
        }
        appartenance = fusionner_voix(par_voix)
        assert appartenance["v1"] != appartenance["v2"]

    def test_une_grosse_voix_continue_d_absorber_les_fragments_minces(self):
        """La garde de matière ne doit pas empêcher le recollage ordinaire :
        une voix déjà établie absorbe sans contrainte nouvelle."""
        par_voix = {
            "etablie": [voix(1.0, 0.0, duree=120.0)],
            "fragment": [voix(0.99, 0.1, duree=1.0)],
        }
        appartenance = fusionner_voix(par_voix)
        assert appartenance["fragment"] == appartenance["etablie"] == "etablie"

    def test_la_garde_de_matiere_est_documentee(self):
        assert MATIERE_MINIMALE_FUSION > 0


class TestBanqueAmbigue:
    """Une banque où deux noms portent la même voix ne peut plus trancher.

    Mesuré sur une banque réelle le 2026-09-02 : deux entrées à 0,77 de
    ressemblance, quand deux personnes différentes s'y mesurent entre 0,22 et
    0,53. L'une portait la voix de l'autre, nommée par erreur trois jours plus
    tôt — et depuis, chaque réunion attribuait ce nom à la mauvaise personne,
    en l'affirmant.
    """

    def test_deux_noms_sur_la_meme_voix_sont_signales(self):
        une = voix(1.0, 0.0, 0.0)
        presque = voix(0.99, 0.14, 0.0)
        banque = [Personne(nom="Camilo", empreintes=[une]),
                  Personne(nom="Tanguy", empreintes=[presque]),
                  Personne(nom="Sophie", empreintes=[voix(0.0, 0.0, 1.0)])]
        conflits = noms_en_conflit(banque)
        assert conflits == {"Camilo": {"Tanguy"}, "Tanguy": {"Camilo"}}
        assert "Sophie" not in conflits

    def test_une_banque_saine_ne_signale_rien(self):
        banque = [Personne(nom="Sophie", empreintes=[voix(1.0, 0.0, 0.0)]),
                  Personne(nom="Kerann", empreintes=[voix(0.0, 1.0, 0.0)])]
        assert noms_en_conflit(banque) == {}

    def test_aucun_nom_n_est_affirme_quand_la_banque_se_contredit(self):
        """Se taire vaut mieux que choisir : c'est l'utilisateur qui tranchera."""
        une = voix(1.0, 0.0, 0.0)
        banque = [Personne(nom="Camilo", empreintes=[une]),
                  Personne(nom="Tanguy", empreintes=[voix(0.99, 0.14, 0.0)]),
                  Personne(nom="Sophie", empreintes=[voix(0.0, 0.0, 1.0)])]
        assert reconnaitre(une, banque) is None

    def test_les_noms_hors_conflit_restent_reconnus(self):
        """Une entrée douteuse ne doit pas rendre toute la banque muette."""
        sophie = voix(0.0, 0.0, 1.0)
        banque = [Personne(nom="Camilo", empreintes=[voix(1.0, 0.0, 0.0)]),
                  Personne(nom="Tanguy", empreintes=[voix(0.99, 0.14, 0.0)]),
                  Personne(nom="Sophie", empreintes=[sophie])]
        correspondance = reconnaitre(sophie, banque)
        assert correspondance is not None and correspondance.nom == "Sophie"

    def test_la_banque_peut_etre_un_generateur(self):
        """Elle est parcourue deux fois : le classement, puis les conflits."""
        sophie = voix(0.0, 0.0, 1.0)
        personnes = [Personne(nom="Sophie", empreintes=[sophie]),
                     Personne(nom="Kerann", empreintes=[voix(0.0, 1.0, 0.0)])]
        correspondance = reconnaitre(sophie, (p for p in personnes))
        assert correspondance is not None and correspondance.nom == "Sophie"
