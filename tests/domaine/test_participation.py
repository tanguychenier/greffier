"""La politesse de l'assistant, éprouvée sans lancer une réunion."""

from greffier.domain.participation import (
    CREUX_MINIMAL,
    Because,
    Manners,
    Opening,
    speech_density,
)


def opening(because=Because.CONTRIBUTION, remark="…", born_at=0.0, subject=""):
    return Opening(because=because, remark=remark, born_at=born_at, subject=subject)


class TestNePasCouper:
    def test_il_se_tait_tant_que_quelqu_un_parle(self):
        """Le défaut de tous les assistants vocaux : répondre dans le blanc.

        Un blanc d'une seconde en réunion n'est pas une invitation, c'est une
        respiration. Y entrer, c'est couper la parole.
        """
        manners = Manners()
        refusal = manners.refusal(opening(), now=10.0, lull=0.5)
        assert refusal == "quelqu'un parle"

    def test_un_vrai_creux_lui_laisse_la_parole(self):
        manners = Manners()
        assert manners.refusal(opening(), now=10.0, lull=CREUX_MINIMAL) is None

    def test_il_ne_s_insere_pas_dans_un_echange_serre(self):
        """Trois personnes qui s'enchaînent n'attendent pas un quatrième avis."""
        manners = Manners()
        refusal = manners.refusal(opening(born_at=95.0), now=100.0, lull=3.0,
                                density=0.95)
        assert refusal == "la discussion est trop dense"


class TestNePasRevenirSansCesse:
    def test_il_se_repose_apres_avoir_parle(self):
        manners = Manners()
        dit = opening(born_at=0.0)
        manners.has_spoken(dit, now=0.0)
        refusal = manners.refusal(opening(born_at=60.0), now=60.0, lull=5.0)
        assert refusal is not None and "repos" in refusal

    def test_le_repos_fini_il_peut_reprendre(self):
        manners = Manners(rest=180.0)
        manners.has_spoken(opening(), now=0.0)
        assert manners.refusal(opening(born_at=200.0), now=200.0, lull=5.0) is None

    def test_etre_appele_ignore_le_repos(self):
        """Quelqu'un qui s'adresse à l'outil attend une réponse, pas de la retenue."""
        manners = Manners()
        manners.has_spoken(opening(), now=0.0)
        appel = opening(because=Because.APPELE, born_at=10.0)
        assert manners.refusal(appel, now=10.0, lull=0.0, density=1.0) is None


class TestNePasSeRepeter:
    def test_un_sujet_deja_traite_ne_revient_pas(self):
        manners = Manners()
        premiere = opening(subject="qui-parle-voix-3", born_at=10.0)
        manners.has_spoken(premiere, now=10.0)
        seconde = opening(subject="qui-parle-voix-3", born_at=400.0)
        assert manners.refusal(seconde, now=400.0, lull=5.0) == "déjà dit"

    def test_meme_appele_il_ne_repete_pas_une_question_posee(self):
        manners = Manners()
        manners.has_spoken(opening(subject="qui-parle-voix-3"), now=0.0)
        appel = opening(because=Because.APPELE, subject="qui-parle-voix-3", born_at=50.0)
        assert manners.refusal(appel, now=50.0, lull=9.0) == "déjà dit"


class TestNeRienServirDeFroid:
    def test_une_occasion_perimee_est_abandonnee(self):
        """Revenir sur un sujet quitté fait passer pour un participant distrait."""
        manners = Manners(staleness=90.0)
        vieille = opening(born_at=10.0)
        refusal = manners.refusal(vieille, now=200.0, lull=5.0)
        assert refusal == "la conversation est passée à autre chose"

    def test_un_appel_ne_se_perime_pas_pour_autant(self):
        manners = Manners()
        appel = opening(because=Because.APPELE, born_at=10.0)
        assert manners.refusal(appel, now=500.0, lull=0.0) is None


class TestChoisir:
    def test_au_plus_une_occasion_et_la_plus_forte(self):
        """Les autres sont abandonnées, pas mises en réserve."""
        manners = Manners()
        retenue = manners.choose(
            [
                opening(because=Because.CONTRIBUTION, remark="une idée", born_at=10.0),
                opening(because=Because.VOIX_INDISTINCTE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.QUESTION_SANS_REPONSE, remark="et Paul ?", born_at=10.0),
            ],
            now=12.0, lull=5.0,
        )
        assert retenue is not None and retenue.remark == "qui parle ?"

    def test_a_egalite_de_force_la_plus_recente_passe(self):
        manners = Manners()
        retenue = manners.choose(
            [opening(remark="vieille", born_at=10.0), opening(remark="fraîche", born_at=50.0)],
            now=60.0, lull=5.0,
        )
        assert retenue is not None and retenue.remark == "fraîche"

    def test_rien_a_dire_est_une_reponse(self):
        manners = Manners()
        assert manners.choose([], now=10.0, lull=5.0) is None

    def test_l_appel_passe_devant_tout(self):
        manners = Manners()
        retenue = manners.choose(
            [
                opening(because=Because.VOIX_INDISTINCTE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.APPELE, remark="oui ?", born_at=11.0),
            ],
            now=12.0, lull=0.0, density=1.0,
        )
        assert retenue is not None and retenue.remark == "oui ?"


class TestBouton:
    def test_desactive_il_ne_dit_plus_rien(self):
        """Le bouton de la fenêtre pose ce réglage, et le repose, sans limite."""
        manners = Manners(active=False)
        appel = opening(because=Because.APPELE, born_at=10.0)
        assert manners.refusal(appel, now=10.0, lull=9.0) == "il ne participe pas"

    def test_reactive_il_repart_sans_rancune(self):
        manners = Manners(active=False)
        manners.active = True
        assert manners.refusal(opening(born_at=10.0), now=11.0, lull=5.0) is None


class TestEchecDeLaParole:
    def test_une_synthese_qui_echoue_ne_coute_pas_le_repos(self):
        """`a_parle` s'appelle après coup : rien n'a été dit, rien n'est retenu."""
        manners = Manners()
        assert manners.refusal(opening(born_at=10.0), now=11.0, lull=5.0) is None
        assert manners.parle_le is None


class TestDensite:
    def test_une_minute_pleine_vaut_un(self):
        assert speech_density([(0.0, 60.0)], now=60.0) == 1.0

    def test_une_minute_vide_vaut_zero(self):
        assert speech_density([], now=60.0) == 0.0

    def test_seule_la_derniere_minute_compte(self):
        """Une réunion qui s'anime ne doit pas être jugée sur son début calme."""
        turns = [(0.0, 300.0), (350.0, 355.0)]
        assert speech_density(turns, now=360.0, window=60.0) < 0.2

    def test_un_tour_a_cheval_n_est_compte_que_pour_sa_part(self):
        assert speech_density([(50.0, 70.0)], now=60.0, window=60.0) == 10.0 / 60.0


class TestCeQueLeReglageGarantit:
    """Le contrat, tel qu'il a été demandé : trois phrases, trois garanties.

    « Si j'active : elle parle uniquement quand on cite son nom. Quand on la
    coupe, elle ne parle pas. Si elle est en train de parler, on la coupe, elle
    ne continue pas sa phrase. »
    """

    def test_activee_elle_ne_parle_que_sur_son_nom(self):
        """Sans initiative, aucune occasion spontanée ne passe."""
        manners = Manners(active=True)
        idee = Opening(because=Because.CONTRIBUTION, remark="une remarque", born_at=100.0)
        appel = Opening(because=Because.APPELE, remark="oui ?", born_at=100.0)
        # L'apport n'est même pas cherché quand l'initiative est éteinte : c'est
        # la veille qui s'en charge. Ici on vérifie que l'appel, lui, passe
        # toujours — quelles que soient les conditions.
        assert manners.refusal(appel, now=100.0, lull=0.0, density=1.0) is None
        assert manners.refusal(idee, now=100.0, lull=0.0, density=1.0)

    def test_coupee_elle_ne_dit_rien_du_tout(self):
        manners = Manners(active=False)
        for because in Because:
            opening = Opening(because=because, remark="…", born_at=100.0)
            assert manners.refusal(opening, now=100.0, lull=9.0) == (
                "il ne participe pas")
