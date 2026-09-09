"""Extraire les points d'une réunion : ne rien inventer, ne rien acter à tort."""

import pytest

from greffier.application.cartographier import RenduIllisible, analyser, extraire
from greffier.domaine.carte import Etat, Genre


class RedacteurFactice:
    def __init__(self, rendu: str) -> None:
        self.rendu = rendu
        self.recu = ""

    def rediger(self, transcription: str) -> str:
        self.recu = transcription
        return self.rendu


class TestAnalyse:
    def test_un_tableau_propre_est_lu(self):
        apports = analyser(
            '[{"texte": "Le PDF ne se régénère pas", "genre": "problème", '
            '"etat": "en discussion", "sous": ""}]'
        )
        assert len(apports) == 1
        assert apports[0].genre is Genre.PROBLEME
        assert apports[0].etat is Etat.EN_DISCUSSION

    def test_un_bloc_de_code_est_accepte(self):
        """Le rédacteur enrobe volontiers, malgré la consigne."""
        apports = analyser('```json\n[{"texte": "Un point"}]\n```')
        assert [a.texte for a in apports] == ["Un point"]

    def test_du_bavardage_autour_du_tableau_est_toleré(self):
        apports = analyser('Voici la liste :\n[{"texte": "Un point"}]\nVoilà.')
        assert [a.texte for a in apports] == ["Un point"]

    def test_une_reponse_sans_tableau_leve(self):
        """Une panne ne doit pas se lire comme « rien à ajouter ».

        Mesuré : le modèle a répondu en prose, en demandant si c'était bien le
        tableau attendu, et la commande a annoncé « rien à ajouter ».
        """
        with pytest.raises(RenduIllisible, match="aucun tableau"):
            analyser("Je n'ai rien trouvé sur ce sujet.")

    def test_un_json_casse_leve(self):
        """Des crochets présents mais un contenu invalide."""
        with pytest.raises(RenduIllisible, match="invalide"):
            analyser('[{"texte": "incomplet", }]')

    def test_une_reponse_tronquee_avant_le_crochet_fermant_leve(self):
        with pytest.raises(RenduIllisible, match="aucun tableau"):
            analyser('[{"texte": "incomplet"')

    def test_un_tableau_vide_est_un_resultat_et_non_une_panne(self):
        assert analyser("[]") == []

    def test_un_element_casse_ne_perd_pas_les_autres(self):
        apports = analyser('[{"texte": "Bon"}, "pas un objet", {"texte": "Aussi bon"}]')
        assert [a.texte for a in apports] == ["Bon", "Aussi bon"]

    def test_un_element_sans_texte_est_ecarte(self):
        assert analyser('[{"genre": "piste"}]') == []

    def test_la_liste_est_plafonnee(self):
        """Une carte illisible ne sert à rien."""
        rendu = "[" + ",".join(f'{{"texte": "point {n}"}}' for n in range(40)) + "]"
        assert len(analyser(rendu, maximum=12)) == 12


class TestPrudenceSurLEtat:
    """Présenter une idée orale comme une décision est le pire défaut ici."""

    def test_le_defaut_est_en_discussion(self):
        assert analyser('[{"texte": "Une idée"}]')[0].etat is Etat.EN_DISCUSSION

    def test_un_etat_non_reconnu_retombe_en_discussion(self):
        apports = analyser('[{"texte": "Une idée", "etat": "peut-être"}]')
        assert apports[0].etat is Etat.EN_DISCUSSION

    def test_depasse_ne_peut_pas_venir_d_une_extraction(self):
        """Seul un humain marque une piste comme dépassée."""
        apports = analyser('[{"texte": "Une piste", "etat": "dépassé"}]')
        assert apports[0].etat is Etat.EN_DISCUSSION

    def test_acte_est_respecte_quand_il_est_explicite(self):
        apports = analyser('[{"texte": "Monter la recette", "etat": "acté"}]')
        assert apports[0].etat is Etat.ACTE

    def test_un_genre_non_reconnu_devient_un_constat(self):
        assert analyser('[{"texte": "X", "genre": "truc"}]')[0].genre is Genre.CONSTAT


class TestExtraction:
    def test_le_sujet_et_la_matiere_sont_transmis(self):
        redacteur = RedacteurFactice('[{"texte": "Un point"}]')
        extraire(redacteur, "Oasis", "On a parlé d'Oasis longuement.")
        assert "Oasis" in redacteur.recu
        assert "On a parlé d'Oasis longuement." in redacteur.recu

    def test_les_consignes_ne_sont_pas_repetees_dans_l_appel(self):
        """Elles sont portées par le rédacteur, pas par l'appelant.

        Répétées ici, elles arrivaient après celles du compte rendu et le
        modèle suivait les premières.
        """
        redacteur = RedacteurFactice('[{"texte": "Un point"}]')
        extraire(redacteur, "Oasis", "matière")
        assert "Tu extrais" not in redacteur.recu

    def test_une_matiere_vide_n_appelle_pas_le_redacteur(self):
        redacteur = RedacteurFactice("[]")
        assert extraire(redacteur, "Oasis", "   ") == []
        assert redacteur.recu == "", "aucun appel ne doit partir"

    def test_les_consignes_interdisent_les_noms_de_personnes(self):
        from greffier.application.cartographier import CONSIGNES

        aplati = " ".join(CONSIGNES.split())
        assert "ni nom de personne ni citation" in aplati

    def test_les_consignes_imposent_le_doute_en_faveur_de_la_discussion(self):
        from greffier.application.cartographier import CONSIGNES

        aplati = " ".join(CONSIGNES.split())
        assert "En cas de doute, « en discussion »" in aplati


class TestCompleterSansDupliquer:
    """Le défaut central : la carte se remplissait de doublons.

    Mesuré à la seconde publication : treize points devenus vingt-six, le
    rédacteur ayant reformulé « Pré-production du client en retard de deux
    versions » en « Pré-prod cliente en retard de deux versions ».
    """

    def test_les_libelles_existants_sont_donnes_au_redacteur(self):
        redacteur = RedacteurFactice('[{"texte": "Un point"}]')
        extraire(redacteur, "Oasis", "matière",
                 deja=("Pré-production du client en retard de deux versions",))
        assert "Pré-production du client en retard" in redacteur.recu

    def test_il_lui_est_demande_de_les_reprendre_mot_pour_mot(self):
        redacteur = RedacteurFactice("[]")
        extraire(redacteur, "Oasis", "matière", deja=("Un point existant",))
        assert "mot pour mot" in redacteur.recu

    def test_sans_carte_existante_rien_n_est_ajoute_a_l_invite(self):
        redacteur = RedacteurFactice("[]")
        extraire(redacteur, "Oasis", "matière")
        assert "Déjà sur la carte" not in redacteur.recu

    def test_la_consigne_dit_de_ne_pas_reprendre_a_tort(self):
        """Reprendre un libellé pour un point différent serait pire."""
        from greffier.application.cartographier import CONSIGNES

        aplati = " ".join(CONSIGNES.split())
        assert "Ne le reprends que s'il s'agit vraiment du même point" in aplati
