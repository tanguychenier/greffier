"""The board of a subject: things are added, nothing is destroyed."""

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


class TestRecognisingTheSamePoint:
    def test_accents_and_case_do_not_count(self):
        assert key("L'accès au SI") == key("acces au si")

    def test_word_order_does_not_count(self):
        """« recette externalisée » et « externalisée, la recette » : un point."""
        assert key("recette externalisée") == key("externalisée recette")

    def test_two_distinct_points_stay_distinct(self):
        assert key("monter la recette") != key("monter la production")

    def test_a_label_made_of_empty_words_keeps_its_identity(self):
        """"A" and "D" are two French empty words.

        With an empty key, two distinct branches became one and the second overwrote
        the first. Joining wrongly loses information, which is worse than duplicating
        it.
        """
        assert key("A") != key("D")
        assert key("A") != ""

    def test_empty_words_are_dropped_when_meaning_remains(self):
        assert key("le déploiement") == key("déploiement")


class TestJoiningAContribution:
    def test_a_new_point_is_added(self):
        board = Board("Oasis")
        bilan = join(board, [Contribution("Le PDF ne se régénère pas")])
        assert bilan.ajoutes == ("Le PDF ne se régénère pas",)
        assert board.count == 2

    def test_a_point_already_there_is_not_duplicated(self):
        board = Board("Oasis")
        join(board, [Contribution("Le PDF ne se régénère pas")])
        bilan = join(board, [Contribution("le pdf ne se regenere pas")])
        assert bilan.ajoutes == ()
        assert board.count == 2, "la reformulation ne crée pas une seconde branche"

    def test_a_lead_hangs_under_its_problem(self):
        board = Board("Oasis")
        join(board, [Contribution("Le PDF ne se régénère pas", kind=Kind.PROBLEM)])
        join(board, [Contribution("Forcer la régénération", kind=Kind.LEAD,
                                 under="Le PDF ne se régénère pas")])
        assert board.root is not None
        probleme = board.root.enfant("Le PDF ne se régénère pas")
        assert probleme is not None
        assert [enfant.text for enfant in probleme.children] == ["Forcer la régénération"]

    def test_a_missing_parent_does_not_lose_the_contribution(self):
        """Mal placé, il reste corrigeable ; perdu, il faut réécouter la réunion."""
        board = Board("Oasis")
        join(board, [Contribution("Une piste", under="un parent qui n'existe pas")])
        assert board.root is not None
        assert board.root.enfant("Une piste") is not None

    def test_the_meeting_it_came_from_is_noted(self):
        board = Board("Oasis")
        join(board, [Contribution("Un point")], meeting="2026-09-09_10h05_reunion")
        assert board.root is not None
        noeud = board.root.enfant("Un point")
        assert noeud is not None
        assert noeud.meetings == ["2026-09-09_10h05_reunion"]

    def test_two_meetings_on_one_point_are_both_noted(self):
        board = Board("Oasis")
        join(board, [Contribution("Un point")], meeting="premiere")
        join(board, [Contribution("Un point")], meeting="seconde")
        assert board.root is not None
        noeud = board.root.enfant("Un point")
        assert noeud is not None
        assert noeud.meetings == ["premiere", "seconde"]

    def test_an_empty_contribution_is_ignored(self):
        board = Board("Oasis")
        assert join(board, [Contribution("   ")]).empty


class TestStandings:
    """What is under discussion must not pass for a decision."""

    def test_the_default_is_under_discussion(self):
        board = Board("Oasis")
        join(board, [Contribution("Une idée lancée à l'oral")])
        assert board.root is not None
        noeud = board.root.enfant("Une idée lancée à l'oral")
        assert noeud is not None
        assert noeud.state is Standing.UNDER_DISCUSSION

    def test_a_decision_raises_the_standing(self):
        board = Board("Oasis")
        join(board, [Contribution("Monter la recette en interne", kind=Kind.LEAD)])
        bilan = join(board, [Contribution("Monter la recette en interne",
                                         kind=Kind.LEAD, state=Standing.AGREED)])
        assert bilan.actes == ("Monter la recette en interne",)
        assert board.root is not None
        noeud = board.root.enfant("Monter la recette en interne")
        assert noeud is not None
        assert noeud.state is Standing.AGREED

    def test_a_problem_cannot_be_agreed(self):
        """"Acté" would read as "the group decided this problem".

        Measured on a real extraction: seven problems out of twelve came back marked
        "acté", the writer having read "acté" as "established".
        """
        board = Board("Oasis")
        join(board, [Contribution("Le PDF ne se régénère pas",
                                 kind=Kind.PROBLEM, state=Standing.AGREED)])
        assert board.root is not None
        noeud = board.root.enfant("Le PDF ne se régénère pas")
        assert noeud is not None
        assert noeud.state is Standing.UNDER_DISCUSSION

    def test_a_lead_and_an_action_can_be_agreed(self):
        board = Board("Oasis")
        join(board, [
            Contribution("Monter la recette", kind=Kind.LEAD, state=Standing.AGREED),
            Contribution("Chiffrer le coût", kind=Kind.ACTION, state=Standing.AGREED)])
        assert board.root is not None
        for text in ("Monter la recette", "Chiffrer le coût"):
            noeud = board.root.enfant(text)
            assert noeud is not None and noeud.state is Standing.AGREED

    def test_a_problem_can_be_overtaken(self):
        """Un problème peut avoir cessé d'en être un."""
        board = Board("Oasis")
        join(board, [Contribution("Un souci", kind=Kind.PROBLEM)])
        assert mark_overdue(board, "Un souci") is True

    def test_a_decision_does_not_go_back_to_a_discussion(self):
        """« Acté » qui redeviendrait « en discussion » ferait douter de tout."""
        board = Board("Oasis")
        join(board, [Contribution("Monter la recette", kind=Kind.LEAD, state=Standing.AGREED)])
        join(board, [Contribution("Monter la recette", kind=Kind.LEAD,
                                 state=Standing.UNDER_DISCUSSION)])
        assert board.root is not None
        noeud = board.root.enfant("Monter la recette")
        assert noeud is not None
        assert noeud.state is Standing.AGREED


class TestNothingEverDisappears:
    """Une carte partagée porte le travail de plusieurs personnes."""

    def test_marking_it_overtaken_keeps_the_node(self):
        board = Board("Oasis")
        join(board, [Contribution("Une piste écartée")])
        assert mark_overdue(board, "Une piste écartée") is True
        assert board.count == 2, "le nœud reste"
        assert board.root is not None
        noeud = board.root.enfant("Une piste écartée")
        assert noeud is not None
        assert noeud.state is Standing.OVERTAKEN

    def test_the_root_cannot_be_marked(self):
        assert mark_overdue(Board("Oasis"), "Oasis") is False

    def test_marking_what_does_not_exist_says_so(self):
        assert mark_overdue(Board("Oasis"), "jamais évoqué") is False

    def test_a_join_removes_no_existing_node(self):
        board = Board("Oasis")
        join(board, [Contribution("A"), Contribution("B"), Contribution("C")])
        avant = board.count
        join(board, [Contribution("D")])
        assert board.count == avant + 1, "rien n'a été remplacé"


class TestCountingTheNodes:
    def test_a_lone_node_counts_for_one(self):
        assert Node("seul").count() == 1

    def test_the_children_count(self):
        root = Node("racine", children=[Node("a"), Node("b", children=[Node("c")])])
        assert root.count() == 4


class TestTheSamePointSaidTwice:
    """The writer rewords from one extraction to the next, and every rewording opened
    one more branch: a quarter of the points came back as duplicates, measured on a
    real board.
    """

    def test_a_real_rewording_is_caught(self):
        from greffier.domain.board import same_point

        assert same_point(
            "Pré-production du client en retard de deux versions",
            "Pré-prod cliente en retard de deux versions",
        )

    def test_another_wording_of_the_same_point(self):
        from greffier.domain.board import same_point

        assert same_point(
            "Monter un environnement de recette chez nous",
            "Monter un environnement de recette de notre côté",
        )

    def test_two_distinct_points_do_not_join(self):
        """Fusionner à tort perd de l'information : c'est le pire défaut ici."""
        from greffier.domain.board import same_point

        assert not same_point(
            "Recette impossible sur l'environnement du client",
            "Pré-prod du client en retard de deux versions",
        )

    def test_a_fragment_does_not_absorb_the_whole(self):
        from greffier.domain.board import same_point

        assert not same_point(
            "la recette",
            "la recette d'Oasis bloquée faute d'environnement à jour",
        )

    def test_a_rewording_too_far_off_stays_a_duplicate(self):
        """An owned limit: catching it would take a threshold that joins distinct points.
        The writer receives the existing labels; the matching is only a net.
        """
        from greffier.domain.board import same_point

        assert not same_point(
            "Questionnaires alimentés par des fixtures écrites à la main",
            "Questionnaires construits avec des fixtures fragiles",
        )

    def test_joining_no_longer_creates_a_reworded_duplicate(self):
        board = Board("Oasis")
        join(board, [Contribution("Pré-production du client en retard de deux versions")])
        bilan = join(board, [Contribution("Pré-prod cliente en retard de deux versions")])
        assert bilan.ajoutes == ()
        assert board.count == 2

    def test_a_short_word_brings_nothing_closer(self):
        """"prod" and "prof" are one apart and have nothing to do with each other."""
        from greffier.domain.board import same_point

        assert not same_point("prod", "prof")
