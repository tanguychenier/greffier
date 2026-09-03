"""Ce qui, pendant la réunion, appelle une action."""

from greffier.domaine.instructions import (
    Genre,
    Origine,
    Veille,
    decisions_dans,
    instruction_apres,
    liens_dans,
)
from greffier.domaine.modeles import Intervalle, Replique


def replique(debut, texte):
    return Replique(intervalle=Intervalle(debut, debut + 5), texte=texte)


class TestLiens:
    def test_une_adresse_collee_est_relevee(self):
        assert liens_dans("voir https://miro.com/board/abc123") == ["https://miro.com/board/abc123"]

    def test_la_ponctuation_finale_ne_fait_pas_partie_du_lien(self):
        assert liens_dans("c'est ici : https://exemple.fr/page.") == ["https://exemple.fr/page"]

    def test_plusieurs_adresses_sans_doublon_et_dans_l_ordre(self):
        texte = "https://a.fr puis https://b.fr et encore https://a.fr"
        assert liens_dans(texte) == ["https://a.fr", "https://b.fr"]

    def test_un_lien_dicte_a_l_oral_n_est_pas_pretendu_reconnu(self):
        """« miro point com slash board » ne donne pas une adresse valable :
        mieux vaut ne rien proposer que proposer n'importe quoi."""
        assert liens_dans("va voir sur miro point com slash board slash b n 7 x") == []

    def test_un_texte_sans_lien_ne_produit_rien(self):
        assert liens_dans("on se revoit jeudi pour la recette") == []


class TestMotDActivation:
    def test_ce_qui_suit_le_mot_est_l_instruction(self):
        assert instruction_apres("Greffier, ouvre le ticket 1234", "greffier") == \
            "ouvre le ticket 1234"

    def test_le_mot_est_reconnu_sans_egard_a_la_casse(self):
        assert instruction_apres("greffier note cette décision", "greffier") == \
            "note cette décision"

    def test_l_instruction_s_arrete_a_la_fin_de_la_phrase(self):
        """Au-delà, la personne est passée à autre chose."""
        texte = "Greffier, note ça. Sinon, on parle du budget maintenant."
        assert instruction_apres(texte, "greffier") == "note ça"

    def test_sans_le_mot_il_n_y_a_pas_d_instruction(self):
        assert instruction_apres("on ouvre le ticket 1234", "greffier") is None

    def test_le_mot_seul_sans_suite_ne_produit_rien(self):
        assert instruction_apres("Greffier.", "greffier") is None


class TestDecisions:
    def test_les_formulations_de_decision_sont_reperees(self):
        for texte in ["on décide de décaler", "il faut qu'on prévienne",
                      "je m'en charge", "à faire : relancer", "d'ici jeudi"]:
            assert decisions_dans(texte), texte

    def test_une_phrase_ordinaire_n_est_pas_une_decision(self):
        assert not decisions_dans("le déploiement s'est bien passé hier")


class TestVeille:
    def test_une_instruction_est_relevee_une_seule_fois(self):
        """La transcription au fil de l'eau repasse sur les mêmes passages."""
        veille = Veille()
        repliques = [replique(10, "Greffier, ouvre le ticket 1234")]
        assert len(veille.ecouter(repliques)) == 1
        assert veille.ecouter(repliques) == []

    def test_un_lien_colle_deux_fois_n_est_proposé_qu_une(self):
        veille = Veille()
        assert len(veille.coller("https://miro.com/x", 5)) == 1
        assert veille.coller("https://miro.com/x", 30) == []

    def test_l_origine_est_conservee(self):
        """Le presse-papier est exact, la parole est transcrite : la fiabilité
        n'est pas la même et le lecteur doit pouvoir en juger."""
        veille = Veille()
        veille.coller("https://a.fr", 1)
        veille.ecouter([replique(2, "Greffier, note le sujet")])
        origines = {p.origine for p in veille.propositions}
        assert origines == {Origine.PRESSE_PAPIER, Origine.PAROLE}

    def test_une_instruction_n_est_pas_reclassee_en_decision(self):
        veille = Veille()
        veille.ecouter([replique(3, "Greffier, note qu'il faut qu'on relance")])
        assert [p.genre for p in veille.propositions] == [Genre.INSTRUCTION]

    def test_le_contexte_de_l_instruction_est_gardé(self):
        veille = Veille()
        veille.ecouter([replique(3, "Bon, Greffier, ouvre le tableau")])
        assert "Bon," in veille.propositions[0].contexte

    def test_on_peut_choisir_un_autre_mot_d_activation(self):
        veille = Veille(mot_cle="assistant")
        veille.ecouter([replique(1, "Assistant, note ce point")])
        assert veille.propositions[0].texte == "note ce point"

    def test_le_tri_par_genre(self):
        veille = Veille()
        veille.coller("https://a.fr https://b.fr", 1)
        veille.ecouter([replique(2, "on décide de reporter la mise en production")])
        assert len(veille.par_genre(Genre.LIEN)) == 2
        assert len(veille.par_genre(Genre.DECISION)) == 1
