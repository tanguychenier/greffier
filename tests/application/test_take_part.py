"""Le comportement de l'assistant en réunion, sans son ni modèle."""

from greffier.application.take_part import AssistantSettings, Remark
from greffier.domain.models import Span, Utterance
from greffier.domain.participation import Because, Manners, Opening, own_words


def dit(text, start=10.0, end=12.0):
    return Utterance(span=Span(start, end), text=text)


class FakeVoiceAdapter:
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


class FakeBrain:
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
        voice, cerveau = FakeVoiceAdapter(), FakeBrain()
        assistant = AssistantSettings(name="Lucie", voice=voice, cerveau=cerveau,
                                tracer=lambda who, what: traces.append((who, what)))
        opening = Opening(because=Because.APPELE, remark="tu nous entends ?", born_at=10.0)
        rendered = assistant.answer(opening, now=13.0)
        assert rendered.prononce
        assert voice.remark == ["Oui, je vous entends très bien."]
        assert traces == [("lucie", "Oui, je vous entends très bien.")]

    def test_sans_voix_il_participe_quand_meme_par_ecrit(self):
        """Tout le monde ne veut pas d'une voix dans la pièce."""
        traces = []
        assistant = AssistantSettings(name="Lucie", cerveau=FakeBrain(),
                                tracer=lambda who, what: traces.append(what))
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert not rendered.prononce and traces == ["Oui, je vous entends très bien."]

    def test_une_reunion_ordinaire_ne_le_fait_pas_parler(self):
        """Le cas courant, et de très loin : il n'a rien à dire."""
        assistant = AssistantSettings(name="Lucie")
        assert assistant.turn([dit("on passe au point suivant")], now=13.0) is None


class TestNePasSEntendreSoiMeme:
    """Sa voix sort par le haut-parleur et rentre par la boucle de capture.

    Jugé sur ses **mots**, et non sur une fenêtre de temps. La fenêtre était
    estimée d'après la longueur du texte, et le harnais de conversation a
    montré ce qu'elle coûtait : elle englobait la question suivante, si bien
    que la salle se retrouvait ignorée. Elle ne tranche plus que pour un propos
    trop court pour être jugé sur ses mots.
    """

    def test_ce_qu_il_vient_de_dire_ne_lui_revient_pas(self):
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_words.append(
            (9.0, own_words("Oui, je peux répéter ce qui vient d'être décidé."))
        )
        retenue = assistant.turn(
            [dit("oui je peux répéter ce qui vient d'être décidé", 10.0, 12.0)],
            now=16.0,
        )
        assert retenue is None

    def test_une_question_de_la_salle_lui_parvient(self):
        """Même juste après qu'il a parlé : c'est l'autre moitié du problème."""
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_words.append((9.0, own_words("Oui, je vous entends.")))
        assert assistant.turn([dit("Lucie, tu peux répéter ?", 10.0, 12.0)],
                              now=13.0) is not None

    def test_un_echo_trop_court_est_rattrape_par_le_temps(self):
        """« Oui » n'a pas assez de mots pour être jugé : la fenêtre sert là."""
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_turns.append((9.0, 15.0))
        assert assistant._is_his_own(dit("oui", 10.0, 12.0), 16.0)

    def test_la_fenetre_ne_decide_plus_quand_les_mots_suffisent(self):
        """Le défaut mesuré : elle englobait la question suivante."""
        assistant = AssistantSettings(name="Lucie")
        assistant.its_own_turns.append((9.0, 15.0))
        assert not assistant._is_his_own(
            dit("Lucie, et où en est la migration en Symfony sept ?", 10.0, 14.0),
            16.0,
        )


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
        suite = assistant.turn([dit("c'est Marcel", 104.0, 105.0)], now=108.0)
        assert nommees == [("12", "Marcel")]
        assert suite is not None
        assert suite.remark == "Merci, c'est noté : je mets Marcel sur cette voix."

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
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter())
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

    def test_switched_off_it_says_nothing_at_all(self):
        assistant = AssistantSettings(name="Lucie", manners=Manners(active=False))
        assert assistant.turn([dit("Lucie ?", 10.0, 11.0)], now=14.0) is None


class TestEchecs:
    def test_un_cerveau_muet_ne_fait_rien_prononcer(self):
        class Broken:
            def write_up(self, _):
                raise RuntimeError("modèle absent")

        voice = FakeVoiceAdapter()
        assistant = AssistantSettings(name="Lucie", voice=voice, cerveau=Broken())
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert rendered == Remark(remark="", because=Because.APPELE, a=2.0)
        assert voice.remark == []

    def test_une_synthese_qui_echoue_laisse_la_trace_ecrite(self):
        """Ce qu'il avait à dire ne se perd pas parce que le son a manqué."""
        traces = []
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(marche=False),
                                cerveau=FakeBrain(),
                                tracer=lambda who, what: traces.append(what))
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="?", born_at=1.0), now=2.0)
        assert not rendered.prononce and traces == ["Oui, je vous entends très bien."]


class TestUnProposDejaEcritNeRepasseParPersonne:
    """Une phrase écrite pour être dite n'a rien à gagner d'un aller-retour.

    Le remerciement qui nomme la voix — « je mets Hubert sur cette voix » — était
    repassé par le modèle, qui le remplaçait par une politesse vague et perdait
    la seule information qui comptait.
    """

    def test_le_remerciement_est_prononce_mot_pour_mot(self):
        voice, cerveau = FakeVoiceAdapter(), FakeBrain("Parfait, je vous laisse.")
        assistant = AssistantSettings(
            name="Lucie", voice=voice, cerveau=cerveau,
            name_voice=lambda _v, _p: True,
        )
        assistant.awaiting = assistant.ask_who_is_speaking("12", now=100.0)
        suite = assistant.turn([dit("c'est Hubert", 104.0, 105.0)], now=108.0)
        assert suite is not None
        rendered = assistant.answer(suite, now=108.0)
        assert rendered.remark == "Merci, c'est noté : je mets Hubert sur cette voix."
        assert cerveau.requests == [], "le modèle a été appelé pour rien"

    def test_la_question_sur_une_voix_ne_passe_pas_non_plus(self):
        """Elle doit être immédiate : rien de distant ne la formule."""
        cerveau = FakeBrain("autre chose")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau)
        question = assistant.ask_who_is_speaking("7", now=50.0)
        rendered = assistant.answer(question, now=50.0)
        assert "prénom" in rendered.remark and cerveau.requests == []

    def test_une_vraie_question_passe_toujours_par_le_modele(self):
        cerveau = FakeBrain("Oui, je vous entends.")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau,
                                context=lambda: "réunion")
        rendered = assistant.answer(
            Opening(because=Because.APPELE, remark="tu nous entends ?", born_at=1.0),
            now=2.0)
        assert rendered.remark == "Oui, je vous entends." and len(cerveau.requests) == 1


class TestLEchangeSePoursuit:
    """Poser une question puis rester muet quand on répond fait passer pour
    distrait, et laisse celui qui a répondu se demander s'il a été entendu."""

    def test_elle_reagit_a_la_reponse_qu_on_lui_fait(self):
        cerveau = FakeBrain("Très bien, donc c'est Hubert qui s'en occupe.")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([dit("c'est Hubert qui prend", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert suite.remark == "Très bien, donc c'est Hubert qui s'en occupe."
        assert suite.as_is, "une suite déjà formulée ne repasse pas par le modèle"

    def test_la_question_posee_est_donnee_au_modele(self):
        """Sans elle, il réagirait à une réponse dont il ignore la question."""
        cerveau = FakeBrain("…")
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([dit("Hubert", 104.0, 106.0)], now=109.0)
        assert any("Qui porte la migration ?" in c for c in cerveau.consignes_vues)

    def test_un_rien_la_fait_se_taire(self):
        """Deux répliques de plus feraient d'elle un participant de trop."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                cerveau=FakeBrain("RIEN"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assert assistant.turn([dit("bon, on passe", 104.0, 106.0)],
                              now=109.0) is None

    def test_sans_cerveau_elle_ne_poursuit_pas(self):
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter())
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        assert assistant.turn([dit("Hubert", 104.0, 106.0)], now=109.0) is None

    def test_elle_n_attend_pas_indefiniment(self):
        """Une phrase quelconque referme l'attente : on ne guette pas sans fin."""
        assistant = AssistantSettings(name="Lucie", voice=FakeVoiceAdapter(),
                                cerveau=FakeBrain("RIEN"))
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
            name="Lucie", voice=FakeVoiceAdapter(),
            cerveau=FakeBrain("Et qui valide, une fois que c'est fait ?"))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        suite = assistant.turn([dit("Hubert s'en charge", 104.0, 106.0)],
                               now=109.0)
        assert suite is not None
        assert assistant.awaiting is suite, "l'échange s'est refermé trop tôt"

    def test_une_conclusion_referme_l_echange(self):
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            cerveau=FakeBrain("Très bien, c'est noté."))
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte la migration ?", born_at=100.0)
        assistant.turn([dit("Hubert s'en charge", 104.0, 106.0)], now=109.0)
        assert assistant.awaiting is None

    def test_le_repos_ne_coupe_pas_un_echange_en_cours(self):
        """Une réponse à sa propre question passe outre le repos.

        Sinon l'assistant poserait une question puis refuserait d'entendre la
        réponse pendant trois minutes, ce qui est pire que de ne rien demander.
        """
        assistant = AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(),
            cerveau=FakeBrain("Et pour quand ?"))
        assistant.manners.has_spoken(
            Opening(because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0),
            now=100.0)
        assistant.awaiting = Opening(
            because=Because.CONTRIBUTION, remark="Qui porte ça ?", born_at=100.0)
        suite = assistant.turn([dit("Hubert", 104.0, 106.0)], now=109.0)
        assert suite is not None, "le repos a coupé l'échange"


class TestLaBoucleEstImpossible:
    """Les cas auxquels on n'avait pas pensé, et qu'une réunion a trouvés.

    Elle parle par le haut-parleur, et l'outil enregistre la sortie système
    exprès — c'est ainsi qu'il entend les autres dans une visio. Sa voix
    revient donc sur le canal des autres. Chaque garde ci-dessous suffirait
    seul ; ensemble ils rendent le cycle impossible, quoi qu'il arrive par
    ailleurs.
    """

    QUESTION = "Lucie, est-ce que tu peux faire des recherches sur Internet ?"

    def _elle(self, cerveau=None, voice=None):
        return AssistantSettings(
            name="Lucie", cerveau=cerveau, voice=voice,
            manners=Manners(creux_minimal=0.0),
        )

    def test_sans_cerveau_elle_se_tait_au_lieu_de_repeter(self):
        """Elle répétait la question, son nom compris, et se rappelait ainsi."""
        elle = self._elle()
        rendu = elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        assert rendu.remark == ""

    def test_ce_qu_elle_dit_ne_porte_jamais_son_nom(self):
        class CerveauQuiRepete:
            def write_up(self, _demande):
                return "Lucie ne peut pas chercher sur Internet."

        voice = FakeVoiceAdapter()
        elle = self._elle(cerveau=CerveauQuiRepete(), voice=voice)
        rendu = elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        assert "Lucie" not in rendu.remark
        assert voice.remark and "Lucie" not in voice.remark[0]

    def test_elle_ne_reagit_pas_a_ses_propres_mots(self):
        """Le cas exact : sa phrase revient par la boucle de capture."""
        class Cerveau:
            def write_up(self, _demande):
                return "Je n'ai pas accès à Internet depuis cette réunion."

        elle = self._elle(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        revenu = [dit("Je n'ai pas accès à Internet depuis cette réunion.", 10.0, 14.0)]
        assert elle.turn(revenu, 15.0) is None

    def test_une_transcription_deformee_de_ses_mots_ne_la_rappelle_pas(self):
        class Cerveau:
            def write_up(self, _demande):
                return "Je n'ai pas accès à Internet depuis cette réunion."

        elle = self._elle(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        abime = [dit("je n ai pas acces a internet depuis cette", 10.0, 14.0)]
        assert elle.turn(abime, 15.0) is None

    def test_la_salle_reste_entendue(self):
        """Le garde ne doit pas la rendre sourde : c'est tout l'enjeu."""
        class Cerveau:
            def write_up(self, _demande):
                return "Je n'ai pas accès à Internet."

        elle = self._elle(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark=self.QUESTION, born_at=1.0), 2.0
        )
        de_la_salle = [dit("Lucie, tu peux nous rappeler la date ?", 20.0, 24.0)]
        retenue = elle.turn(de_la_salle, 25.0)
        assert retenue is not None and retenue.because is Because.APPELE

    def test_elle_oublie_ses_mots_au_bout_d_un_moment(self):
        """Sinon un participant qui reprend son idée serait pris pour elle."""
        class Cerveau:
            def write_up(self, _demande):
                return "La migration en Symfony sept reste à confier à quelqu'un."

        elle = self._elle(cerveau=Cerveau(), voice=FakeVoiceAdapter())
        elle.answer(
            Opening(because=Because.APPELE, remark="Lucie, où en est la migration ?",
                    born_at=1.0),
            2.0,
        )
        tard = [dit("la migration en Symfony sept reste à confier à quelqu'un", 600.0, 606.0)]
        assert elle._is_his_own(tard[0], 610.0) is False


class TestElleALeDroitDeChercher:
    """Elle disait ne pas pouvoir chercher sur Internet, outils en main.

    Rapporté après une réunion. Les outils `WebSearch` et `WebFetch` étaient
    bien accordés — `conversation.recherche_web` vaut vrai par défaut — mais la
    consigne **orale**, qui remplace celle de la conversation écrite, lui
    disait de s'en tenir à ce qui avait été dit. Elle obéissait.
    """

    def test_la_consigne_orale_autorise_la_recherche(self):
        from greffier.application.take_part import CONSIGNES_ORALES

        consigne = CONSIGNES_ORALES.format(name="Lucie")
        assert "chercher en ligne" in consigne
        assert "de ton propre chef" in consigne

    def test_elle_nomme_la_source_sans_dire_l_adresse(self):
        """Une URL ne s'entend pas ; une source sans nom ne se vérifie pas."""
        from greffier.application.take_part import CONSIGNES_ORALES

        consigne = CONSIGNES_ORALES.format(name="Lucie")
        assert "nomme la source à voix haute" in consigne
        assert "jamais son" in consigne and "adresse" in consigne

    def test_elle_ne_doit_plus_s_en_tenir_a_la_reunion(self):
        ancien = "Si tu n'as pas la réponse dans ce qui a été dit, dis-le"
        from greffier.application.take_part import CONSIGNES_ORALES

        assert ancien not in CONSIGNES_ORALES

    def test_les_outils_sont_accordes_quand_le_reglage_le_dit(self):
        from greffier.adapters.configuration import Config
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.wiring import assistant

        cerveau = assistant(Config(conversation={"recherche_web": True}))
        assert isinstance(cerveau, ClaudeWriter)
        assert cerveau.tools == ClaudeWriter.SEARCH_TOOLS

    def test_le_reglage_les_retire_vraiment(self):
        """Qui ne veut rien laisser sortir du poste doit pouvoir l'obtenir."""
        from greffier.adapters.configuration import Config
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.wiring import assistant

        cerveau = assistant(Config(conversation={"recherche_web": False}))
        assert isinstance(cerveau, ClaudeWriter)
        assert cerveau.tools == ()


class TestStoppedForGood:
    """`stop()` is the end of the meeting, and it must reach a remark in flight.

    Phrasing happens in a separate thread and takes seconds: cutting the
    speaker is not enough, because the thread comes back afterwards and speaks
    into a room where the meeting is over.
    """

    def _elle(self, cerveau=None):
        return AssistantSettings(
            name="Lucie", voice=FakeVoiceAdapter(), cerveau=cerveau or FakeBrain(),
            manners=Manners(active=True),
        )

    def _appel(self, now=12.0):
        return Opening(because=Because.APPELE, remark="Lucie, une idée ?", born_at=now)

    def test_nothing_is_pronounced_after_a_stop(self):
        elle = self._elle()
        elle.stop()
        assert elle.answer(self._appel(), now=12.0).remark == ""
        assert elle.voice.remark == []

    def test_the_speaker_is_cut_by_the_stop(self):
        elle = self._elle()
        coupee = []
        elle.voice.go_quiet = lambda: coupee.append(True)
        elle.stop()
        assert coupee == [True]

    def test_a_remark_phrased_during_the_stop_stays_in(self):
        """The thread was already inside the brain when the meeting ended."""
        elle = self._elle()

        class BrainThatEnds(FakeBrain):
            def write_up(self, text):
                elle.stop()
                return super().write_up(text)

        elle.cerveau = BrainThatEnds()
        assert elle.answer(self._appel(), now=12.0).remark == ""
        assert elle.voice.remark == []

    def test_a_stop_without_a_voice_does_not_raise(self):
        elle = self._elle()
        elle.voice = None
        elle.stop()
        assert elle.stopped

    def test_a_speaker_that_fails_to_stop_does_not_raise(self):
        """The neural voice goes through a subprocess: killing it can fail."""
        elle = self._elle()

        def tomber():
            raise OSError("kill: no such process")

        elle.voice.go_quiet = tomber
        elle.stop()
        assert elle.stopped

    def test_before_the_stop_she_does_answer(self):
        elle = self._elle()
        assert elle.answer(self._appel(), now=12.0).remark
        assert elle.voice.remark


class TestSheKnowsTheSetting:
    """The glossary of the organisation goes to the assistant, not only to the
    writer of the minutes.

    This room says "CASA", "visa", "OTP" and "recette" for things no general
    model knows, and the writer has been told about them since the beginning
    while the assistant answered on the words alone.
    """

    def _elle(self, milieu=None):
        return AssistantSettings(
            name="Lucie", cerveau=FakeBrain(), manners=Manners(active=True),
            setting=milieu,
        )

    def test_the_glossary_opens_the_guidance(self):
        elle = self._elle(lambda: "[Contexte] CASA : gestion des logements.\n\n")
        consignes = elle.guidance()
        assert consignes.startswith("[Contexte] CASA")
        assert "Lucie" in consignes, "elle garde ses propres consignes"

    def test_without_a_setting_the_guidance_does_not_change(self):
        assert "Contexte" not in self._elle().guidance()

    def test_an_empty_setting_adds_nothing(self):
        assert self._elle(lambda: "").guidance() == self._elle().guidance()

    def test_a_setting_that_fails_to_read_does_not_silence_her(self):
        """The context file can be missing or unreadable: she still answers."""

        def tomber():
            raise OSError("contexte.toml illisible")

        consignes = self._elle(tomber).guidance()
        assert "Lucie" in consignes and consignes

    def test_the_setting_is_read_when_asked_for_and_not_before(self):
        """It is read at each call, so a term added mid-meeting is taken in."""
        appels = []
        elle = self._elle(lambda: appels.append(1) or "[Contexte] X.\n\n")
        assert not appels
        elle.guidance()
        elle.guidance()
        assert len(appels) == 2
