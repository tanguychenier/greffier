"""Ce qui, pendant la réunion, appelle une action."""

from greffier.domain.instructions import (
    Kind,
    Origin,
    WatchRules,
    decisions_in,
    instruction_after,
    liens_dans,
)
from greffier.domain.models import Span, Utterance
from greffier.domain.profiles.french import FRENCH


def utterance(start, text):
    return Utterance(span=Span(start, start + 5), text=text)


class TestLiens:
    def test_une_adresse_collee_est_relevee(self):
        assert liens_dans("voir https://miro.com/board/abc123") == ["https://miro.com/board/abc123"]

    def test_la_ponctuation_finale_ne_fait_pas_partie_du_lien(self):
        assert liens_dans("c'est ici : https://exemple.fr/page.") == ["https://exemple.fr/page"]

    def test_plusieurs_adresses_sans_doublon_et_dans_l_ordre(self):
        text = "https://a.fr puis https://b.fr et encore https://a.fr"
        assert liens_dans(text) == ["https://a.fr", "https://b.fr"]

    def test_un_lien_dicte_a_l_oral_n_est_pas_pretendu_reconnu(self):
        """« miro point com slash board » ne donne pas une adresse valable :
        mieux vaut ne rien proposer que proposer n'importe quoi."""
        assert liens_dans("va voir sur miro point com slash board slash b n 7 x") == []

    def test_un_texte_sans_lien_ne_produit_rien(self):
        assert liens_dans("on se revoit jeudi pour la recette") == []


class TestMotDActivation:
    def test_ce_qui_suit_le_mot_est_l_instruction(self):
        assert instruction_after("Greffier, ouvre le ticket 1234", "greffier") == \
            "ouvre le ticket 1234"

    def test_le_mot_est_reconnu_sans_egard_a_la_casse(self):
        assert instruction_after("greffier note cette décision", "greffier") == \
            "note cette décision"

    def test_l_instruction_s_arrete_a_la_fin_de_la_phrase(self):
        """Au-delà, la personne est passée à autre chose."""
        text = "Greffier, note ça. Sinon, on parle du budget maintenant."
        assert instruction_after(text, "greffier") == "note ça"

    def test_sans_le_mot_il_n_y_a_pas_d_instruction(self):
        assert instruction_after("on ouvre le ticket 1234", "greffier") is None

    def test_le_mot_seul_sans_suite_ne_produit_rien(self):
        assert instruction_after("Greffier.", "greffier") is None


class TestDecisions:
    def test_les_formulations_de_decision_sont_reperees(self):
        for text in ["on décide de décaler", "il faut qu'on prévienne",
                      "je m'en charge", "à faire : relancer", "d'ici jeudi"]:
            assert decisions_in(text, FRENCH), text

    def test_une_phrase_ordinaire_n_est_pas_une_decision(self):
        assert not decisions_in("le déploiement s'est bien passé hier", FRENCH)


class TestVeille:
    def test_une_instruction_est_relevee_une_seule_fois(self):
        """La transcription au fil de l'eau repasse sur les mêmes passages."""
        watch_rules = WatchRules(profil=FRENCH)
        utterances = [utterance(10, "Greffier, ouvre le ticket 1234")]
        assert len(watch_rules.listen(utterances)) == 1
        assert watch_rules.listen(utterances) == []

    def test_un_lien_colle_deux_fois_n_est_proposé_qu_une(self):
        watch_rules = WatchRules(profil=FRENCH)
        assert len(watch_rules.paste("https://miro.com/x", 5)) == 1
        assert watch_rules.paste("https://miro.com/x", 30) == []

    def test_l_origine_est_conservee(self):
        """Le presse-papier est exact, la parole est transcrite : la fiabilité
        n'est pas la même et le lecteur doit pouvoir en juger."""
        watch_rules = WatchRules(profil=FRENCH)
        watch_rules.paste("https://a.fr", 1)
        watch_rules.listen([utterance(2, "Greffier, note le sujet")])
        origines = {p.origine for p in watch_rules.propositions}
        assert origines == {Origin.PRESSE_PAPIER, Origin.PAROLE}

    def test_une_instruction_n_est_pas_reclassee_en_decision(self):
        watch_rules = WatchRules(profil=FRENCH)
        watch_rules.listen([utterance(3, "Greffier, note qu'il faut qu'on relance")])
        assert [p.kind for p in watch_rules.propositions] == [Kind.INSTRUCTION]

    def test_le_contexte_de_l_instruction_est_gardé(self):
        watch_rules = WatchRules(profil=FRENCH)
        watch_rules.listen([utterance(3, "Bon, Greffier, ouvre le tableau")])
        assert "Bon," in watch_rules.propositions[0].context

    def test_on_peut_choisir_un_autre_mot_d_activation(self):
        watch_rules = WatchRules(mot_cle="assistant", profil=FRENCH)
        watch_rules.listen([utterance(1, "Assistant, note ce point")])
        assert watch_rules.propositions[0].text == "note ce point"

    def test_le_tri_par_genre(self):
        watch_rules = WatchRules(profil=FRENCH)
        watch_rules.paste("https://a.fr https://b.fr", 1)
        watch_rules.listen([utterance(2, "on décide de reporter la mise en production")])
        assert len(watch_rules.by_gender(Kind.LIEN)) == 2
        assert len(watch_rules.by_gender(Kind.DECISION)) == 1
