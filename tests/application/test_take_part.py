"""Le comportement de l'assistant en réunion, sans son ni modèle."""

from greffier.application.take_part import AssistantSettings, Remark
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Manners, Opening


def dit(text, start=10.0, end=12.0):
    return Utterance(span=Span(start, end), text=text)


class VoixFactice:
    def __init__(self, marche=True):
        self.marche = marche
        self.remark = []

    def say(self, text):
        self.remark.append(text)
        return self.marche

    def go_quiet(self):
        ...

    def is_speaking(self):
        return False


class CerveauFactice:
    """Comme `RedacteurClaude` : il porte des consignes qu'on remplace.

    L'attribut compte : `_interroger` s'en sert pour poser des consignes le
    temps d'un appel, et retombe sur un préfixe quand il n'existe pas. Une
    doublure sans lui n'éprouverait pas le chemin réel.
    """

    def __init__(self, response="Oui, je vous entends très bien."):
        self.response = response
        self.consignes_propres = ""
        self.requests = []
        #: Les consignes en vigueur à chaque appel, et non à la fin : elles sont
        #: reposées après coup, donc les lire ensuite ne dit rien.
        self.consignes_vues = []

    def write_up(self, text):
        self.requests.append(text)
        self.consignes_vues.append(self.consignes_propres)
        return self.response


class TestEtreAppele:
    def test_son_nom_prononce_le_fait_repondre(self):
        """« Lucie, est-ce que tu nous entends ? » — le cas qu'on démontre."""
        assistant = AssistantSettings(name="Lucie")
        retenue = assistant.turn([dit("Lucie, est-ce que tu nous entends bien ?")],
                                 now=13.0)
        assert retenue is not None
        assert retenue.because is Because.APPELE
        assert retenue.remark == "est-ce que tu nous entends bien ?"

    def test_il_repond_par_la_voix_et_laisse_une_trace(self):
        traces = []
        voice, cerveau = VoixFactice(), CerveauFactice()
        assistant = AssistantSettings(name="Lucie", voice=voice, cerveau=cerveau,
                                tracer=lambda qui, quoi: traces.append((qui, quoi)))
        opening = Opening(because=Because.APPELE, remark="tu nous entends ?", born_at=10.0)
        rendered = assistant.answer(opening, now=13.0)
        assert rendered.prononce
        assert voice.remark == ["Oui, je vous entends très bien."]
        assert traces == [("lucie", "Oui, je vous entends très bien.")]

    def test_sans_voix_il_participe_quand_meme_par_ecrit(self):
        """Tout le monde ne veut pas d'une voix dans la pièce."""
        traces = []
        assistant = AssistantSettings(name="Lucie", cerveau=CerveauFactice(),
                                tracer=lambda qui, quoi: traces.append(quoi))
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert not rendered.prononce and traces == ["Oui, je vous entends très bien."]

    def test_une_reunion_ordinaire_ne_le_fait_pas_parler(self):
        """Le cas courant, et de très loin : il n'a rien à dire."""
        assistant = AssistantSettings(name="Lucie")
        assert assistant.turn([dit("on passe au point suivant")], now=13.0) is None


class TestNePasSEntendreSoiMeme:
    def test_ce_qu_il_vient_de_dire_ne_lui_revient_pas(self):
        """Sa voix sort par le haut-parleur et rentre par le micro.

        Sans cette garde, il se répond à lui-même, et il gagne au passage une
        empreinte vocale dans le compte rendu.
        """
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_turns.append((9.0, 15.0))
        retenue = assistant.turn([dit("Lucie, tu peux répéter ?", 10.0, 12.0)],
                                 now=16.0)
        assert retenue is None

    def test_une_phrase_hors_de_sa_prise_lui_parvient(self):
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_turns.append((0.0, 5.0))
        assert assistant.turn([dit("Lucie, tu peux répéter ?", 10.0, 12.0)],
                              now=13.0) is not None


class TestLeCycleQuiVautDExister:
    def test_il_demande_qui_parle_puis_nomme_la_voix_et_remercie(self):
        """Demander coûte une phrase et vaut un nom au compte rendu."""
        nommees = []
        assistant = AssistantSettings(
            name="Lucie",
            name_voice=lambda voice, first_name: (nommees.append((voice, first_name)), True)[1],
        )
        question = assistant.ask_who_is_speaking("12", now=100.0)
        assistant.awaiting = question
        suite = assistant.turn([dit("c'est Michel", 104.0, 105.0)], now=108.0)
        assert nommees == [("12", "Michel")]
        assert suite is not None
        assert suite.remark == "Merci, c'est noté : je mets Michel sur cette voix."

    def test_une_reponse_incomprehensible_ne_nomme_personne(self):
        """Mieux vaut ne rien nommer que d'appeler quelqu'un « Alors »."""
        nommees = []
        assistant = AssistantSettings(
            name="Lucie", name_voice=lambda v, p: (nommees.append((v, p)), True)[1])
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([dit("alors attends je ne sais plus", 104.0, 106.0)],
                               now=108.0)
        assert nommees == [] and suite is None

    def test_la_question_ne_reste_pas_en_attente_indefiniment(self):
        """Une phrase quelconque referme l'attente : on ne guette pas sans fin."""
        assistant = AssistantSettings(name="Lucie", name_voice=lambda v, p: True)
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        assistant.turn([dit("bon, on reprend", 104.0, 106.0)], now=108.0)
        assert assistant.awaiting is None

    def test_demander_qui_parle_ne_demande_pas_de_modele(self):
        """Cette question doit être immédiate : rien de distant ne la formule."""
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice())
        question = assistant.ask_who_is_speaking("7", now=50.0)
        rendered = assistant.answer(question, now=50.0)
        assert "prénom" in rendered.remark and assistant.cerveau is None


class TestPolitesse:
    def test_il_ne_coupe_pas_la_parole(self):
        """Le creux se mesure sur la fin de la dernière réplique entendue.

        Sur une occasion spontanée : être appelé passe outre, et c'est voulu —
        quelqu'un qui s'adresse à l'outil n'attend pas qu'il juge le moment
        opportun.
        """
        assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=2.0))
        idee = Opening(because=Because.CONTRIBUTION, remark="une idée", born_at=11.0)
        # La phrase finit à 12 s et on est à 12,5 s : quelqu'un parle encore.
        assert assistant.turn([dit("on continue", 11.0, 12.0)], now=12.5,
                              occasions=[idee]) is None

    def test_un_appel_passe_outre_le_creux(self):
        assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=2.0))
        assert assistant.turn([dit("Lucie ?", 11.0, 12.0)], now=12.5) is not None

    def test_le_repos_ne_bloque_pas_un_appel(self):
        assistant = AssistantSettings(name="Lucie")
        assistant.manners.has_spoken(
            Opening(because=Because.CONTRIBUTION, remark="…"), now=0.0)
        assert assistant.turn([dit("Lucie ?", 10.0, 11.0)], now=20.0) is not None

    def test_desactive_il_ne_dit_plus_rien(self):
        assistant = AssistantSettings(name="Lucie", manners=Manners(active=False))
        assert assistant.turn([dit("Lucie ?", 10.0, 11.0)], now=14.0) is None


class TestEchecs:
    def test_un_cerveau_muet_ne_fait_rien_prononcer(self):
        class Casse:
            def write_up(self, _):
                raise RuntimeError("modèle absent")

        voice = VoixFactice()
        assistant = AssistantSettings(name="Lucie", voice=voice, cerveau=Casse())
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert rendered == Remark(remark="", because=Because.APPELE, a=2.0)
        assert voice.remark == []

    def test_une_synthese_qui_echoue_laisse_la_trace_ecrite(self):
        """Ce qu'il avait à dire ne se perd pas parce que le son a manqué."""
        traces = []
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(marche=False),
                                cerveau=CerveauFactice(),
                                tracer=lambda qui, quoi: traces.append(quoi))
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert not rendered.prononce and traces == ["Oui, je vous entends très bien."]


class TestUnProposDejaEcritNeRepasseParPersonne:
    """Une phrase écrite pour être dite n'a rien à gagner d'un aller-retour.

    Le remerciement qui nomme la voix — « je mets Hugo sur cette voix » — était
    repassé par le modèle, qui le remplaçait par une politesse vague et perdait
    la seule information qui comptait.
    """

    def test_le_remerciement_est_prononce_mot_pour_mot(self):
        voice, cerveau = VoixFactice(), CerveauFactice("Parfait, je vous laisse.")
        assistant = AssistantSettings(
            name="Lucie", voice=voice, cerveau=cerveau,
            name_voice=lambda _v, _p: True,
        )
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([dit("c'est Hugo", 104.0, 105.0)], now=108.0)
        assert suite is not None
        rendered = assistant.answer(suite, now=108.0)
        assert rendered.remark == "Merci, c'est noté : je mets Hugo sur cette voix."
        assert cerveau.requests == [], "le modèle a été appelé pour rien"

    def test_la_question_sur_une_voix_ne_passe_pas_non_plus(self):
        """Elle doit être immédiate : rien de distant ne la formule."""
        cerveau = CerveauFactice("autre chose")
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(), cerveau=cerveau)
        question = assistant.ask_who_is_speaking("7", now=50.0)
        rendered = assistant.answer(question, now=50.0)
        assert "prénom" in rendered.remark and cerveau.requests == []

    def test_une_vraie_question_passe_toujours_par_le_modele(self):
        cerveau = CerveauFactice("Oui, je vous entends.")
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(), cerveau=cerveau,
                                context=lambda: "réunion")
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="tu nous entends ?", born_at=1.0),
            now=2.0)
        assert rendered.remark == "Oui, je vous entends." and len(cerveau.requests) == 1


class TestLEchangeSePoursuit:
    """Poser une question puis rester muet quand on répond fait passer pour
    distrait, et laisse celui qui a répondu se demander s'il a été entendu."""

    def test_elle_reagit_a_la_reponse_qu_on_lui_fait(self):
        cerveau = CerveauFactice("Très bien, donc c'est Hugo qui s'en occupe.")
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(), cerveau=cerveau)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([dit("c'est Hugo qui prend", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert suite.remark == "Très bien, donc c'est Hugo qui s'en occupe."
        assert suite.as_is, "une suite déjà formulée ne repasse pas par le modèle"

    def test_la_question_posee_est_donnee_au_modele(self):
        """Sans elle, il réagirait à une réponse dont il ignore la question."""
        cerveau = CerveauFactice("…")
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(), cerveau=cerveau)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([dit("Hugo", 104.0, 106.0)], now=109.0)
        assert any("Qui porte la migration ?" in c for c in cerveau.consignes_vues)

    def test_un_rien_la_fait_se_taire(self):
        """Deux répliques de plus feraient d'elle un participant de trop."""
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(),
                                cerveau=CerveauFactice("RIEN"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assert assistant.turn([dit("bon, on passe", 104.0, 106.0)],
                              now=109.0) is None

    def test_sans_cerveau_elle_ne_poursuit_pas(self):
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice())
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        assert assistant.turn([dit("Hugo", 104.0, 106.0)], now=109.0) is None

    def test_elle_n_attend_pas_indefiniment(self):
        """Une phrase quelconque referme l'attente : on ne guette pas sans fin."""
        assistant = AssistantSettings(name="Lucie", voice=VoixFactice(),
                                cerveau=CerveauFactice("RIEN"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        assistant.turn([dit("autre chose", 104.0, 106.0)], now=109.0)
        assert assistant.awaiting is None


class TestElleContinueTantQuElleADesQuestions:
    """Un dialogue, pas un aller-retour.

    Le signal d'arrêt vient d'elle — le point d'interrogation final — et non
    d'un compteur qui la couperait au milieu d'un sujet.
    """

    def test_une_question_de_suite_garde_l_echange_ouvert(self):
        assistant = AssistantSettings(
            name="Lucie", voice=VoixFactice(),
            cerveau=CerveauFactice("Et qui valide, une fois que c'est fait ?"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([dit("Hugo s'en charge", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert assistant.awaiting is suite, "l'échange s'est refermé trop tôt"

    def test_une_conclusion_referme_l_echange(self):
        assistant = AssistantSettings(
            name="Lucie", voice=VoixFactice(),
            cerveau=CerveauFactice("Très bien, c'est noté."))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([dit("Hugo s'en charge", 104.0, 106.0)], now=109.0)
        assert assistant.awaiting is None

    def test_le_repos_ne_coupe_pas_un_echange_en_cours(self):
        """Une réponse à sa propre question passe outre le repos.

        Sinon l'assistant poserait une question puis refuserait d'entendre la
        réponse pendant trois minutes, ce qui est pire que de ne rien demander.
        """
        assistant = AssistantSettings(
            name="Lucie", voice=VoixFactice(),
            cerveau=CerveauFactice("Et pour quand ?"))
        assistant.manners.has_spoken(
            Opening(because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0),
            now=100.0)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        suite = assistant.turn([dit("Hugo", 104.0, 106.0)], now=109.0)
        assert suite is not None, "le repos a coupé l'échange"
