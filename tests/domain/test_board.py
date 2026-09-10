"""La carte d'un sujet : on ajoute, on ne détruit pas."""

from greffier.domain.board import (
    Board,
    Contribution,
    Kind,
    Node,
    Standing,
    join,
    key,
    mark_overdue,
)


class TestReconnaissanceDeFormulation:
    def test_les_accents_et_la_casse_ne_comptent_pas(self):
        assert key("L'accès au SI") == key("acces au si")

    def test_l_ordre_des_mots_ne_compte_pas(self):
        """« recette externalisée » et « externalisée, la recette » : un point."""
        assert key("recette externalisée") == key("externalisée recette")

    def test_deux_points_distincts_restent_distincts(self):
        assert key("monter la recette") != key("monter la production")

    def test_un_libelle_fait_de_mots_vides_garde_son_identite(self):
        """« A » et « D » sont deux mots vides français.

        Avec une clef vide, deux branches distinctes n'en faisaient plus qu'une
        et la seconde écrasait la première. Fusionner à tort perd de
        l'information, ce qui est pire que d'en dupliquer.
        """
        assert key("A") != key("D")
        assert key("A") != ""

    def test_les_mots_vides_sont_bien_retires_quand_il_reste_du_sens(self):
        assert key("le déploiement") == key("déploiement")


class TestFusion:
    def test_un_point_nouveau_s_ajoute(self):
        board = Board("Oasis")
        bilan = join(board, [Contribution("Le PDF ne se régénère pas")])
        assert bilan.ajoutes == ("Le PDF ne se régénère pas",)
        assert board.count == 2

    def test_un_point_deja_present_ne_se_duplique_pas(self):
        board = Board("Oasis")
        join(board, [Contribution("Le PDF ne se régénère pas")])
        bilan = join(board, [Contribution("le pdf ne se regenere pas")])
        assert bilan.ajoutes == ()
        assert board.count == 2, "la reformulation ne crée pas une seconde branche"

    def test_une_piste_s_accroche_sous_son_probleme(self):
        board = Board("Oasis")
        join(board, [Contribution("Le PDF ne se régénère pas", kind=Kind.PROBLEM)])
        join(board, [Contribution("Forcer la régénération", kind=Kind.LEAD,
                                 under="Le PDF ne se régénère pas")])
        assert board.root is not None
        probleme = board.root.enfant("Le PDF ne se régénère pas")
        assert probleme is not None
        assert [enfant.text for enfant in probleme.children] == ["Forcer la régénération"]

    def test_un_parent_introuvable_ne_perd_pas_l_apport(self):
        """Mal placé, il reste corrigeable ; perdu, il faut réécouter la réunion."""
        board = Board("Oasis")
        join(board, [Contribution("Une piste", under="un parent qui n'existe pas")])
        assert board.root is not None
        assert board.root.enfant("Une piste") is not None

    def test_la_reunion_d_origine_est_notee(self):
        board = Board("Oasis")
        join(board, [Contribution("Un point")], meeting="2026-09-09_10h05_reunion")
        assert board.root is not None
        noeud = board.root.enfant("Un point")
        assert noeud is not None
        assert noeud.meetings == ["2026-09-09_10h05_reunion"]

    def test_deux_reunions_sur_le_meme_point_sont_toutes_deux_notees(self):
        board = Board("Oasis")
        join(board, [Contribution("Un point")], meeting="premiere")
        join(board, [Contribution("Un point")], meeting="seconde")
        assert board.root is not None
        noeud = board.root.enfant("Un point")
        assert noeud is not None
        assert noeud.meetings == ["premiere", "seconde"]

    def test_un_apport_vide_est_ignore(self):
        board = Board("Oasis")
        assert join(board, [Contribution("   ")]).empty


class TestEtats:
    """Ce qui est en discussion ne doit pas passer pour une décision."""

    def test_le_defaut_est_en_discussion(self):
        board = Board("Oasis")
        join(board, [Contribution("Une idée lancée à l'oral")])
        assert board.root is not None
        noeud = board.root.enfant("Une idée lancée à l'oral")
        assert noeud is not None
        assert noeud.state is Standing.UNDER_DISCUSSION

    def test_une_decision_releve_l_etat(self):
        board = Board("Oasis")
        join(board, [Contribution("Monter la recette en interne", kind=Kind.LEAD)])
        bilan = join(board, [Contribution("Monter la recette en interne",
                                         kind=Kind.LEAD, state=Standing.AGREED)])
        assert bilan.actes == ("Monter la recette en interne",)
        assert board.root is not None
        noeud = board.root.enfant("Monter la recette en interne")
        assert noeud is not None
        assert noeud.state is Standing.AGREED

    def test_un_probleme_ne_peut_pas_etre_acte(self):
        """« Acté » se lirait « le groupe a décidé ce problème ».

        Mesuré sur une extraction réelle : sept problèmes sur douze revenaient
        marqués « acté », le rédacteur ayant lu « acté » comme « établi ».
        """
        board = Board("Oasis")
        join(board, [Contribution("Le PDF ne se régénère pas",
                                 kind=Kind.PROBLEM, state=Standing.AGREED)])
        assert board.root is not None
        noeud = board.root.enfant("Le PDF ne se régénère pas")
        assert noeud is not None
        assert noeud.state is Standing.UNDER_DISCUSSION

    def test_une_piste_et_une_action_peuvent_etre_actees(self):
        board = Board("Oasis")
        join(board, [
            Contribution("Monter la recette", kind=Kind.LEAD, state=Standing.AGREED),
            Contribution("Chiffrer le coût", kind=Kind.ACTION, state=Standing.AGREED)])
        assert board.root is not None
        for text in ("Monter la recette", "Chiffrer le coût"):
            noeud = board.root.enfant(text)
            assert noeud is not None and noeud.state is Standing.AGREED

    def test_un_probleme_peut_etre_depasse(self):
        """Un problème peut avoir cessé d'en être un."""
        board = Board("Oasis")
        join(board, [Contribution("Un souci", kind=Kind.PROBLEM)])
        assert mark_overdue(board, "Un souci") is True

    def test_une_decision_ne_redevient_pas_une_discussion(self):
        """« Acté » qui redeviendrait « en discussion » ferait douter de tout."""
        board = Board("Oasis")
        join(board, [Contribution("Monter la recette", kind=Kind.LEAD, state=Standing.AGREED)])
        join(board, [Contribution("Monter la recette", kind=Kind.LEAD,
                                 state=Standing.UNDER_DISCUSSION)])
        assert board.root is not None
        noeud = board.root.enfant("Monter la recette")
        assert noeud is not None
        assert noeud.state is Standing.AGREED


class TestRienNeDisparait:
    """Une carte partagée porte le travail de plusieurs personnes."""

    def test_marquer_depasse_garde_le_noeud(self):
        board = Board("Oasis")
        join(board, [Contribution("Une piste écartée")])
        assert mark_overdue(board, "Une piste écartée") is True
        assert board.count == 2, "le nœud reste"
        assert board.root is not None
        noeud = board.root.enfant("Une piste écartée")
        assert noeud is not None
        assert noeud.state is Standing.OVERTAKEN

    def test_la_racine_ne_se_marque_pas(self):
        assert mark_overdue(Board("Oasis"), "Oasis") is False

    def test_marquer_ce_qui_n_existe_pas_le_dit(self):
        assert mark_overdue(Board("Oasis"), "jamais évoqué") is False

    def test_une_fusion_ne_retire_aucun_noeud_existant(self):
        board = Board("Oasis")
        join(board, [Contribution("A"), Contribution("B"), Contribution("C")])
        avant = board.count
        join(board, [Contribution("D")])
        assert board.count == avant + 1, "rien n'a été remplacé"


class TestComptage:
    def test_un_noeud_seul_compte_pour_un(self):
        assert Node("seul").count() == 1

    def test_les_enfants_comptent(self):
        root = Node("racine", children=[Node("a"), Node("b", children=[Node("c")])])
        assert root.count() == 4


class TestReformulations:
    """Le rédacteur reformule d'une extraction à l'autre, et chaque
    reformulation ouvrait une branche de plus : un quart des points revenaient
    en doublon, mesuré sur une carte réelle.
    """

    def test_une_reformulation_reelle_est_rattrapee(self):
        from greffier.domain.board import same_point

        assert same_point(
            "Pré-production du client en retard de deux versions",
            "Pré-prod cliente en retard de deux versions",
        )

    def test_une_autre_formulation_du_meme_point(self):
        from greffier.domain.board import same_point

        assert same_point(
            "Monter un environnement de recette chez nous",
            "Monter un environnement de recette de notre côté",
        )

    def test_deux_points_distincts_ne_fusionnent_pas(self):
        """Fusionner à tort perd de l'information : c'est le pire défaut ici."""
        from greffier.domain.board import same_point

        assert not same_point(
            "Recette impossible sur l'environnement du client",
            "Pré-prod du client en retard de deux versions",
        )

    def test_un_fragment_n_absorbe_pas_le_tout(self):
        from greffier.domain.board import same_point

        assert not same_point(
            "la recette",
            "la recette d'Oasis bloquée faute d'environnement à jour",
        )

    def test_une_reformulation_trop_eloignee_reste_un_doublon(self):
        """Limite assumée : la rattraper demanderait un seuil qui fusionnerait
        des points distincts. Le rédacteur reçoit les libellés existants, le
        rapprochement n'est qu'un filet."""
        from greffier.domain.board import same_point

        assert not same_point(
            "Questionnaires alimentés par des fixtures écrites à la main",
            "Questionnaires construits avec des fixtures fragiles",
        )

    def test_la_fusion_ne_cree_plus_de_doublon_de_reformulation(self):
        board = Board("Oasis")
        join(board, [Contribution("Pré-production du client en retard de deux versions")])
        bilan = join(board, [Contribution("Pré-prod cliente en retard de deux versions")])
        assert bilan.ajoutes == ()
        assert board.count == 2

    def test_un_mot_court_ne_rapproche_pas(self):
        """« prod » et « prof » sont à un écart et n'ont aucun rapport."""
        from greffier.domain.board import same_point

        assert not same_point("prod", "prof")
