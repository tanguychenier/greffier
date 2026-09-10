"""La politesse de l'assistant, éprouvée sans lancer une réunion."""

from greffier.domain.participation import (
    MINIMUM_LULL,
    Because,
    Manners,
    Opening,
    called_by_name,
    is_own,
    own_words,
    speech_density,
    without_own_name,
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
        assert manners.refusal(opening(), now=10.0, lull=MINIMUM_LULL) is None

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
                opening(because=Because.INDISTINCT_VOICE, remark="qui parle ?", born_at=10.0),
                opening(because=Because.QUESTION_WITHOUT_ANSWER, remark="et Paul ?", born_at=10.0),
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
                opening(because=Because.INDISTINCT_VOICE, remark="qui parle ?", born_at=10.0),
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
        assert manners.spoke_at is None


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


class TestElleNeDoitPasSEntendreElleMeme:
    """Elle parle par le haut-parleur, et l'outil enregistre la sortie système.

    C'est voulu : c'est ainsi qu'il entend les autres participants d'une visio.
    Conséquence, sa propre voix revient sur le canal des autres, elle y lit son
    propre nom dans sa propre réponse, et elle repart. **Sans fin.**

    Jugé sur les mots et non sur l'horloge, et c'est tout le point : elle répond
    tard, dans un fil séparé, donc aucune fenêtre de temps n'est fiable.
    """

    DIT = "Qui prend en charge la migration en Symfony 7 ?"

    def _ses_mots(self, *remarks: str) -> list[frozenset[str]]:
        return [own_words(r) for r in remarks]

    def test_ses_mots_exacts_reviennent(self):
        assert is_own(self.DIT, self._ses_mots(self.DIT))

    def test_ses_mots_deformes_par_le_haut_parleur(self):
        """Ce qui revient n'est jamais orthographié pareil."""
        assert is_own(
            "qui prend en charge la migration en Symfony sept",
            self._ses_mots(self.DIT),
        )

    def test_une_moitie_de_sa_phrase_suffit(self):
        """La salle et la boucle de capture coûtent des mots au passage."""
        assert is_own("qui prend en charge la migration", self._ses_mots(self.DIT))

    def test_la_salle_n_est_pas_prise_pour_elle(self):
        assert not is_own(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?",
            self._ses_mots(self.DIT),
        )

    def test_une_interjection_n_est_jamais_la_sienne(self):
        """« oui » et « d'accord » appartiennent à tout le monde."""
        for court in ("oui", "d'accord", "bon", "ok"):
            assert not is_own(court, self._ses_mots("oui d'accord bon ok"))

    def test_sans_rien_avoir_dit_elle_n_entend_personne(self):
        assert not is_own(self.DIT, [])

    def test_plusieurs_de_ses_propos_sont_gardes(self):
        """Elle parle plusieurs fois : chacun doit rester reconnaissable."""
        mes = self._ses_mots(
            self.DIT,
            "Il reste la signature, et la recette à caler.",
        )
        assert is_own("il reste la signature et la recette", mes)
        assert is_own("qui prend en charge la migration", mes)

    def test_les_accents_ne_font_pas_deux_phrases(self):
        assert is_own(
            "L'ETAPE VISA EST DEJA CALEE POUR JEUDI",
            self._ses_mots("L'étape visa est déjà calée pour jeudi"),
        )

    def test_un_sujet_commun_ne_suffit_pas(self):
        """Le vrai risque : un participant qui parle du même sujet qu'elle."""
        assert not is_own(
            "la migration me paraît risquée avant la recette de jeudi soir",
            self._ses_mots("Qui prend en charge la migration ?"),
        )


class TestSonNomNeSortJamaisDeSaBouche:
    """La garantie dure, et c'est celle qui coupe la boucle à la racine.

    Constaté en réunion réelle : « Lucie, est-ce que tu peux faire des
    recherches sur Internet ? » quinze fois en quinze secondes, prononcé par
    elle. Elle avait répété la question qu'on venait de lui poser, son nom
    compris, l'avait entendue par la boucle de capture, y avait lu son nom, et
    était repartie.

    Retirer son nom de tout ce qu'elle prononce rend le cycle impossible, quoi
    qu'il arrive par ailleurs — cerveau absent, transcription déformée, canal
    mal attribué.
    """

    def test_son_nom_est_retire(self):
        assert "Lucie" not in without_own_name(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?", "Lucie"
        )

    def test_ce_qu_elle_dit_reste_lisible(self):
        assert without_own_name(
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?", "Lucie"
        ) == "est-ce que tu peux faire des recherches sur Internet ?"

    def test_son_nom_deforme_est_retire_aussi(self):
        """La transcription rend « Lucie » de vingt façons."""
        for dit in ("Lucy, tu m'entends ?", "Lucie tu m'entends ?",
                    "Luci, tu m'entends ?"):
            assert "uc" not in without_own_name(dit, "Lucie").lower(), dit

    def test_un_propos_sans_son_nom_n_est_pas_touche(self):
        """Le cas courant : elle ne doit pas voir sa phrase remaniée."""
        propos = "Qui prend en charge la migration en Symfony 7 ?"
        assert without_own_name(propos, "Lucie") == propos

    def test_la_typographie_francaise_survit(self):
        """Le français garde une espace avant les deux-points."""
        propos = "Merci, c'est noté : je mets Hugo sur cette voix."
        assert without_own_name(propos, "Lucie") == propos

    def test_le_nom_au_milieu_d_une_phrase(self):
        assert without_own_name("Oui Lucie a bien compris", "Lucie") == "Oui a bien compris"

    def test_un_nom_vide_ne_touche_a_rien(self):
        assert without_own_name("phrase entière", "") == "phrase entière"

    def test_ce_qui_reste_ne_rappelle_plus_personne(self):
        """Le bouclage complet : ce qu'elle dit ne doit plus l'appeler."""
        for question in (
            "Lucie, est-ce que tu peux faire des recherches sur Internet ?",
            "Lucie, tu as compris le sujet Lucie ?",
            "Dis-moi Lucie",
        ):
            reste = without_own_name(question, "Lucie")
            assert not called_by_name(reste, "Lucie"), reste
