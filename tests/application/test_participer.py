"""Le comportement de l'assistant en réunion, sans son ni modèle."""

from greffier.application.participer import Intervention, Participant
from greffier.domaine.modeles import Intervalle, Replique
from greffier.domaine.participation import Occasion, Politique, Raison


def dit(texte, debut=10.0, fin=12.0):
    return Replique(intervalle=Intervalle(debut, fin), texte=texte)


class VoixFactice:
    def __init__(self, marche=True):
        self.marche = marche
        self.propos = []

    def dire(self, texte):
        self.propos.append(texte)
        return self.marche

    def se_taire(self):
        ...

    def parle(self):
        return False


class CerveauFactice:
    """Comme `RedacteurClaude` : il porte des consignes qu'on remplace.

    L'attribut compte : `_interroger` s'en sert pour poser des consignes le
    temps d'un appel, et retombe sur un préfixe quand il n'existe pas. Une
    doublure sans lui n'éprouverait pas le chemin réel.
    """

    def __init__(self, reponse="Oui, je vous entends très bien."):
        self.reponse = reponse
        self.consignes_propres = ""
        self.demandes = []
        #: Les consignes en vigueur à chaque appel, et non à la fin : elles sont
        #: reposées après coup, donc les lire ensuite ne dit rien.
        self.consignes_vues = []

    def rediger(self, texte):
        self.demandes.append(texte)
        self.consignes_vues.append(self.consignes_propres)
        return self.reponse


class TestEtreAppele:
    def test_son_nom_prononce_le_fait_repondre(self):
        """« Lucie, est-ce que tu nous entends ? » — le cas qu'on démontre."""
        assistant = Participant(nom="Lucie")
        retenue = assistant.tour([dit("Lucie, est-ce que tu nous entends bien ?")],
                                 maintenant=13.0)
        assert retenue is not None
        assert retenue.raison is Raison.APPELE
        assert retenue.propos == "est-ce que tu nous entends bien ?"

    def test_il_repond_par_la_voix_et_laisse_une_trace(self):
        traces = []
        voix, cerveau = VoixFactice(), CerveauFactice()
        assistant = Participant(nom="Lucie", voix=voix, cerveau=cerveau,
                                tracer=lambda qui, quoi: traces.append((qui, quoi)))
        occasion = Occasion(raison=Raison.APPELE, propos="tu nous entends ?", ne_le=10.0)
        rendu = assistant.repondre(occasion, maintenant=13.0)
        assert rendu.prononce
        assert voix.propos == ["Oui, je vous entends très bien."]
        assert traces == [("lucie", "Oui, je vous entends très bien.")]

    def test_sans_voix_il_participe_quand_meme_par_ecrit(self):
        """Tout le monde ne veut pas d'une voix dans la pièce."""
        traces = []
        assistant = Participant(nom="Lucie", cerveau=CerveauFactice(),
                                tracer=lambda qui, quoi: traces.append(quoi))
        rendu = assistant.repondre(
            Occasion(raison=Raison.APPELE, propos="?", ne_le=1.0), maintenant=2.0)
        assert not rendu.prononce and traces == ["Oui, je vous entends très bien."]

    def test_une_reunion_ordinaire_ne_le_fait_pas_parler(self):
        """Le cas courant, et de très loin : il n'a rien à dire."""
        assistant = Participant(nom="Lucie")
        assert assistant.tour([dit("on passe au point suivant")], maintenant=13.0) is None


class TestNePasSEntendreSoiMeme:
    def test_ce_qu_il_vient_de_dire_ne_lui_revient_pas(self):
        """Sa voix sort par le haut-parleur et rentre par le micro.

        Sans cette garde, il se répond à lui-même, et il gagne au passage une
        empreinte vocale dans le compte rendu.
        """
        assistant = Participant(nom="Lucie")
        assistant.ses_prises.append((9.0, 15.0))
        retenue = assistant.tour([dit("Lucie, tu peux répéter ?", 10.0, 12.0)],
                                 maintenant=16.0)
        assert retenue is None

    def test_une_phrase_hors_de_sa_prise_lui_parvient(self):
        assistant = Participant(nom="Lucie")
        assistant.ses_prises.append((0.0, 5.0))
        assert assistant.tour([dit("Lucie, tu peux répéter ?", 10.0, 12.0)],
                              maintenant=13.0) is not None


class TestLeCycleQuiVautDExister:
    def test_il_demande_qui_parle_puis_nomme_la_voix_et_remercie(self):
        """Demander coûte une phrase et vaut un nom au compte rendu."""
        nommees = []
        assistant = Participant(
            nom="Lucie",
            nommer=lambda voix, prenom: (nommees.append((voix, prenom)), True)[1],
        )
        question = assistant.demander_qui_parle("12", maintenant=100.0)
        assistant.attente = question
        suite = assistant.tour([dit("c'est Marcel", 104.0, 105.0)], maintenant=108.0)
        assert nommees == [("12", "Marcel")]
        assert suite is not None
        assert suite.propos == "Merci, c'est noté : je mets Marcel sur cette voix."

    def test_une_reponse_incomprehensible_ne_nomme_personne(self):
        """Mieux vaut ne rien nommer que d'appeler quelqu'un « Alors »."""
        nommees = []
        assistant = Participant(
            nom="Lucie", nommer=lambda v, p: (nommees.append((v, p)), True)[1])
        assistant.attente = assistant.demander_qui_parle("12", maintenant=100.0)
        suite = assistant.tour([dit("alors attends je ne sais plus", 104.0, 106.0)],
                               maintenant=108.0)
        assert nommees == [] and suite is None

    def test_la_question_ne_reste_pas_en_attente_indefiniment(self):
        """Une phrase quelconque referme l'attente : on ne guette pas sans fin."""
        assistant = Participant(nom="Lucie", nommer=lambda v, p: True)
        assistant.attente = assistant.demander_qui_parle("12", maintenant=100.0)
        assistant.tour([dit("bon, on reprend", 104.0, 106.0)], maintenant=108.0)
        assert assistant.attente is None

    def test_demander_qui_parle_ne_demande_pas_de_modele(self):
        """Cette question doit être immédiate : rien de distant ne la formule."""
        assistant = Participant(nom="Lucie", voix=VoixFactice())
        question = assistant.demander_qui_parle("7", maintenant=50.0)
        rendu = assistant.repondre(question, maintenant=50.0)
        assert "prénom" in rendu.propos and assistant.cerveau is None


class TestPolitesse:
    def test_il_ne_coupe_pas_la_parole(self):
        """Le creux se mesure sur la fin de la dernière réplique entendue.

        Sur une occasion spontanée : être appelé passe outre, et c'est voulu —
        quelqu'un qui s'adresse à l'outil n'attend pas qu'il juge le moment
        opportun.
        """
        assistant = Participant(nom="Lucie", politique=Politique(creux_minimal=2.0))
        idee = Occasion(raison=Raison.APPORT, propos="une idée", ne_le=11.0)
        # La phrase finit à 12 s et on est à 12,5 s : quelqu'un parle encore.
        assert assistant.tour([dit("on continue", 11.0, 12.0)], maintenant=12.5,
                              occasions=[idee]) is None

    def test_un_appel_passe_outre_le_creux(self):
        assistant = Participant(nom="Lucie", politique=Politique(creux_minimal=2.0))
        assert assistant.tour([dit("Lucie ?", 11.0, 12.0)], maintenant=12.5) is not None

    def test_le_repos_ne_bloque_pas_un_appel(self):
        assistant = Participant(nom="Lucie")
        assistant.politique.a_parle(
            Occasion(raison=Raison.APPORT, propos="…"), maintenant=0.0)
        assert assistant.tour([dit("Lucie ?", 10.0, 11.0)], maintenant=20.0) is not None

    def test_desactive_il_ne_dit_plus_rien(self):
        assistant = Participant(nom="Lucie", politique=Politique(actif=False))
        assert assistant.tour([dit("Lucie ?", 10.0, 11.0)], maintenant=14.0) is None


class TestEchecs:
    def test_un_cerveau_muet_ne_fait_rien_prononcer(self):
        class Casse:
            def rediger(self, _):
                raise RuntimeError("modèle absent")

        voix = VoixFactice()
        assistant = Participant(nom="Lucie", voix=voix, cerveau=Casse())
        rendu = assistant.repondre(
            Occasion(raison=Raison.APPELE, propos="?", ne_le=1.0), maintenant=2.0)
        assert rendu == Intervention(propos="", raison=Raison.APPELE, a=2.0)
        assert voix.propos == []

    def test_une_synthese_qui_echoue_laisse_la_trace_ecrite(self):
        """Ce qu'il avait à dire ne se perd pas parce que le son a manqué."""
        traces = []
        assistant = Participant(nom="Lucie", voix=VoixFactice(marche=False),
                                cerveau=CerveauFactice(),
                                tracer=lambda qui, quoi: traces.append(quoi))
        rendu = assistant.repondre(
            Occasion(raison=Raison.APPELE, propos="?", ne_le=1.0), maintenant=2.0)
        assert not rendu.prononce and traces == ["Oui, je vous entends très bien."]


class TestUnProposDejaEcritNeRepasseParPersonne:
    """Une phrase écrite pour être dite n'a rien à gagner d'un aller-retour.

    Le remerciement qui nomme la voix — « je mets Hubert sur cette voix » — était
    repassé par le modèle, qui le remplaçait par une politesse vague et perdait
    la seule information qui comptait.
    """

    def test_le_remerciement_est_prononce_mot_pour_mot(self):
        voix, cerveau = VoixFactice(), CerveauFactice("Parfait, je vous laisse.")
        assistant = Participant(
            nom="Lucie", voix=voix, cerveau=cerveau,
            nommer=lambda _v, _p: True,
        )
        assistant.attente = assistant.demander_qui_parle("12", maintenant=100.0)
        suite = assistant.tour([dit("c'est Hubert", 104.0, 105.0)], maintenant=108.0)
        assert suite is not None
        rendu = assistant.repondre(suite, maintenant=108.0)
        assert rendu.propos == "Merci, c'est noté : je mets Hubert sur cette voix."
        assert cerveau.demandes == [], "le modèle a été appelé pour rien"

    def test_la_question_sur_une_voix_ne_passe_pas_non_plus(self):
        """Elle doit être immédiate : rien de distant ne la formule."""
        cerveau = CerveauFactice("autre chose")
        assistant = Participant(nom="Lucie", voix=VoixFactice(), cerveau=cerveau)
        question = assistant.demander_qui_parle("7", maintenant=50.0)
        rendu = assistant.repondre(question, maintenant=50.0)
        assert "prénom" in rendu.propos and cerveau.demandes == []

    def test_une_vraie_question_passe_toujours_par_le_modele(self):
        cerveau = CerveauFactice("Oui, je vous entends.")
        assistant = Participant(nom="Lucie", voix=VoixFactice(), cerveau=cerveau,
                                contexte=lambda: "réunion")
        rendu = assistant.repondre(
            Occasion(raison=Raison.APPELE, propos="tu nous entends ?", ne_le=1.0),
            maintenant=2.0)
        assert rendu.propos == "Oui, je vous entends." and len(cerveau.demandes) == 1


class TestLEchangeSePoursuit:
    """Poser une question puis rester muet quand on répond fait passer pour
    distrait, et laisse celui qui a répondu se demander s'il a été entendu."""

    def test_elle_reagit_a_la_reponse_qu_on_lui_fait(self):
        cerveau = CerveauFactice("Très bien, donc c'est Hubert qui s'en occupe.")
        assistant = Participant(nom="Lucie", voix=VoixFactice(), cerveau=cerveau)
        assistant.attente = Occasion(
            raison=Raison.APPORT, propos="Qui porte la migration ?", ne_le=100.0)
        suite = assistant.tour([dit("c'est Hubert qui prend", 104.0, 106.0)],
                               maintenant=109.0)
        assert suite is not None
        assert suite.propos == "Très bien, donc c'est Hubert qui s'en occupe."
        assert suite.tel_quel, "une suite déjà formulée ne repasse pas par le modèle"

    def test_la_question_posee_est_donnee_au_modele(self):
        """Sans elle, il réagirait à une réponse dont il ignore la question."""
        cerveau = CerveauFactice("…")
        assistant = Participant(nom="Lucie", voix=VoixFactice(), cerveau=cerveau)
        assistant.attente = Occasion(
            raison=Raison.APPORT, propos="Qui porte la migration ?", ne_le=100.0)
        assistant.tour([dit("Hubert", 104.0, 106.0)], maintenant=109.0)
        assert any("Qui porte la migration ?" in c for c in cerveau.consignes_vues)

    def test_un_rien_la_fait_se_taire(self):
        """Deux répliques de plus feraient d'elle un participant de trop."""
        assistant = Participant(nom="Lucie", voix=VoixFactice(),
                                cerveau=CerveauFactice("RIEN"))
        assistant.attente = Occasion(
            raison=Raison.APPORT, propos="Qui porte la migration ?", ne_le=100.0)
        assert assistant.tour([dit("bon, on passe", 104.0, 106.0)],
                              maintenant=109.0) is None

    def test_sans_cerveau_elle_ne_poursuit_pas(self):
        assistant = Participant(nom="Lucie", voix=VoixFactice())
        assistant.attente = Occasion(
            raison=Raison.APPORT, propos="Qui porte ça ?", ne_le=100.0)
        assert assistant.tour([dit("Hubert", 104.0, 106.0)], maintenant=109.0) is None

    def test_elle_n_attend_pas_indefiniment(self):
        """Une phrase quelconque referme l'attente : on ne guette pas sans fin."""
        assistant = Participant(nom="Lucie", voix=VoixFactice(),
                                cerveau=CerveauFactice("RIEN"))
        assistant.attente = Occasion(
            raison=Raison.APPORT, propos="Qui porte ça ?", ne_le=100.0)
        assistant.tour([dit("autre chose", 104.0, 106.0)], maintenant=109.0)
        assert assistant.attente is None
