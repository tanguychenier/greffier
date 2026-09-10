"""La politesse de l'assistant, éprouvée sans lancer une réunion."""

from greffier.domaine.participation import (
    CREUX_MINIMAL,
    Occasion,
    Politique,
    Raison,
    densite_de_parole,
)


def occasion(raison=Raison.APPORT, propos="…", ne_le=0.0, sujet=""):
    return Occasion(raison=raison, propos=propos, ne_le=ne_le, sujet=sujet)


class TestNePasCouper:
    def test_il_se_tait_tant_que_quelqu_un_parle(self):
        """Le défaut de tous les assistants vocaux : répondre dans le blanc.

        Un blanc d'une seconde en réunion n'est pas une invitation, c'est une
        respiration. Y entrer, c'est couper la parole.
        """
        politique = Politique()
        refus = politique.refus(occasion(), maintenant=10.0, creux=0.5)
        assert refus == "quelqu'un parle"

    def test_un_vrai_creux_lui_laisse_la_parole(self):
        politique = Politique()
        assert politique.refus(occasion(), maintenant=10.0, creux=CREUX_MINIMAL) is None

    def test_il_ne_s_insere_pas_dans_un_echange_serre(self):
        """Trois personnes qui s'enchaînent n'attendent pas un quatrième avis."""
        politique = Politique()
        refus = politique.refus(occasion(ne_le=95.0), maintenant=100.0, creux=3.0,
                                densite=0.95)
        assert refus == "la discussion est trop dense"


class TestNePasRevenirSansCesse:
    def test_il_se_repose_apres_avoir_parle(self):
        politique = Politique()
        dit = occasion(ne_le=0.0)
        politique.a_parle(dit, maintenant=0.0)
        refus = politique.refus(occasion(ne_le=60.0), maintenant=60.0, creux=5.0)
        assert refus is not None and "repos" in refus

    def test_le_repos_fini_il_peut_reprendre(self):
        politique = Politique(repos=180.0)
        politique.a_parle(occasion(), maintenant=0.0)
        assert politique.refus(occasion(ne_le=200.0), maintenant=200.0, creux=5.0) is None

    def test_etre_appele_ignore_le_repos(self):
        """Quelqu'un qui s'adresse à l'outil attend une réponse, pas de la retenue."""
        politique = Politique()
        politique.a_parle(occasion(), maintenant=0.0)
        appel = occasion(raison=Raison.APPELE, ne_le=10.0)
        assert politique.refus(appel, maintenant=10.0, creux=0.0, densite=1.0) is None


class TestNePasSeRepeter:
    def test_un_sujet_deja_traite_ne_revient_pas(self):
        politique = Politique()
        premiere = occasion(sujet="qui-parle-voix-3", ne_le=10.0)
        politique.a_parle(premiere, maintenant=10.0)
        seconde = occasion(sujet="qui-parle-voix-3", ne_le=400.0)
        assert politique.refus(seconde, maintenant=400.0, creux=5.0) == "déjà dit"

    def test_meme_appele_il_ne_repete_pas_une_question_posee(self):
        politique = Politique()
        politique.a_parle(occasion(sujet="qui-parle-voix-3"), maintenant=0.0)
        appel = occasion(raison=Raison.APPELE, sujet="qui-parle-voix-3", ne_le=50.0)
        assert politique.refus(appel, maintenant=50.0, creux=9.0) == "déjà dit"


class TestNeRienServirDeFroid:
    def test_une_occasion_perimee_est_abandonnee(self):
        """Revenir sur un sujet quitté fait passer pour un participant distrait."""
        politique = Politique(peremption=90.0)
        vieille = occasion(ne_le=10.0)
        refus = politique.refus(vieille, maintenant=200.0, creux=5.0)
        assert refus == "la conversation est passée à autre chose"

    def test_un_appel_ne_se_perime_pas_pour_autant(self):
        politique = Politique()
        appel = occasion(raison=Raison.APPELE, ne_le=10.0)
        assert politique.refus(appel, maintenant=500.0, creux=0.0) is None


class TestChoisir:
    def test_au_plus_une_occasion_et_la_plus_forte(self):
        """Les autres sont abandonnées, pas mises en réserve."""
        politique = Politique()
        retenue = politique.choisir(
            [
                occasion(raison=Raison.APPORT, propos="une idée", ne_le=10.0),
                occasion(raison=Raison.VOIX_INDISTINCTE, propos="qui parle ?", ne_le=10.0),
                occasion(raison=Raison.QUESTION_SANS_REPONSE, propos="et Paul ?", ne_le=10.0),
            ],
            maintenant=12.0, creux=5.0,
        )
        assert retenue is not None and retenue.propos == "qui parle ?"

    def test_a_egalite_de_force_la_plus_recente_passe(self):
        politique = Politique()
        retenue = politique.choisir(
            [occasion(propos="vieille", ne_le=10.0), occasion(propos="fraîche", ne_le=50.0)],
            maintenant=60.0, creux=5.0,
        )
        assert retenue is not None and retenue.propos == "fraîche"

    def test_rien_a_dire_est_une_reponse(self):
        politique = Politique()
        assert politique.choisir([], maintenant=10.0, creux=5.0) is None

    def test_l_appel_passe_devant_tout(self):
        politique = Politique()
        retenue = politique.choisir(
            [
                occasion(raison=Raison.VOIX_INDISTINCTE, propos="qui parle ?", ne_le=10.0),
                occasion(raison=Raison.APPELE, propos="oui ?", ne_le=11.0),
            ],
            maintenant=12.0, creux=0.0, densite=1.0,
        )
        assert retenue is not None and retenue.propos == "oui ?"


class TestBouton:
    def test_desactive_il_ne_dit_plus_rien(self):
        """Le bouton de la fenêtre pose ce réglage, et le repose, sans limite."""
        politique = Politique(actif=False)
        appel = occasion(raison=Raison.APPELE, ne_le=10.0)
        assert politique.refus(appel, maintenant=10.0, creux=9.0) == "il ne participe pas"

    def test_reactive_il_repart_sans_rancune(self):
        politique = Politique(actif=False)
        politique.actif = True
        assert politique.refus(occasion(ne_le=10.0), maintenant=11.0, creux=5.0) is None


class TestEchecDeLaParole:
    def test_une_synthese_qui_echoue_ne_coute_pas_le_repos(self):
        """`a_parle` s'appelle après coup : rien n'a été dit, rien n'est retenu."""
        politique = Politique()
        assert politique.refus(occasion(ne_le=10.0), maintenant=11.0, creux=5.0) is None
        assert politique.parle_le is None


class TestDensite:
    def test_une_minute_pleine_vaut_un(self):
        assert densite_de_parole([(0.0, 60.0)], maintenant=60.0) == 1.0

    def test_une_minute_vide_vaut_zero(self):
        assert densite_de_parole([], maintenant=60.0) == 0.0

    def test_seule_la_derniere_minute_compte(self):
        """Une réunion qui s'anime ne doit pas être jugée sur son début calme."""
        tours = [(0.0, 300.0), (350.0, 355.0)]
        assert densite_de_parole(tours, maintenant=360.0, fenetre=60.0) < 0.2

    def test_un_tour_a_cheval_n_est_compte_que_pour_sa_part(self):
        assert densite_de_parole([(50.0, 70.0)], maintenant=60.0, fenetre=60.0) == 10.0 / 60.0


class TestCeQueLeReglageGarantit:
    """Le contrat, tel qu'il a été demandé : trois phrases, trois garanties.

    « Si j'active : elle parle uniquement quand on cite son nom. Quand on la
    coupe, elle ne parle pas. Si elle est en train de parler, on la coupe, elle
    ne continue pas sa phrase. »
    """

    def test_activee_elle_ne_parle_que_sur_son_nom(self):
        """Sans initiative, aucune occasion spontanée ne passe."""
        politique = Politique(actif=True)
        idee = Occasion(raison=Raison.APPORT, propos="une remarque", ne_le=100.0)
        appel = Occasion(raison=Raison.APPELE, propos="oui ?", ne_le=100.0)
        # L'apport n'est même pas cherché quand l'initiative est éteinte : c'est
        # la veille qui s'en charge. Ici on vérifie que l'appel, lui, passe
        # toujours — quelles que soient les conditions.
        assert politique.refus(appel, maintenant=100.0, creux=0.0, densite=1.0) is None
        assert politique.refus(idee, maintenant=100.0, creux=0.0, densite=1.0)

    def test_coupee_elle_ne_dit_rien_du_tout(self):
        politique = Politique(actif=False)
        for raison in Raison:
            occasion = Occasion(raison=raison, propos="…", ne_le=100.0)
            assert politique.refus(occasion, maintenant=100.0, creux=9.0) == (
                "il ne participe pas")
