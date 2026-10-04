"""Laying out a tree so that nothing overlaps."""

from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.board import Board, Contribution, Node, join
from greffier.domain.layout import (
    BETWEEN_COLUMNS,
    BETWEEN_LINES,
    WIDTH,
    lay_out,
)


def trees() -> st.SearchStrategy[Node]:
    """Any tree a board can grow: up to four branches a node, ten leaves in all."""
    leaves = st.builds(Node, st.sampled_from(["constat", "piste", "action"]))
    return st.recursive(
        leaves,
        lambda below: st.builds(Node, st.just("problème"),
                                children=st.lists(below, min_size=1, max_size=4)),
        max_leaves=10,
    )


def a_board_grown_into(root: Node) -> Board:
    """Board builds its own root; the generated tree takes its place once built."""
    board = Board("Oasis")
    board.root = root
    return board


def a_board() -> Board:
    board = Board("Oasis")
    join(board, [Contribution("Problème A"), Contribution("Problème B")])
    join(board, [Contribution("Piste A1", under="Problème A"),
                      Contribution("Piste A2", under="Problème A")])
    return board


class TestLayingOutTheBoard:
    def test_every_node_gets_a_place(self):
        assert len(lay_out(a_board())) == a_board().count

    def test_the_root_is_on_the_left(self):
        places = lay_out(a_board())
        assert places[0].node.text == "Oasis"
        assert places[0].x == 0

    def test_the_depth_gives_the_column(self):
        places = {place.node.text: place for place in lay_out(a_board())}
        assert places["Problème A"].x == BETWEEN_COLUMNS
        assert places["Piste A1"].x == 2 * BETWEEN_COLUMNS

    def test_the_link_to_the_parent_is_given(self):
        places = {place.node.text: place for place in lay_out(a_board())}
        assert places["Piste A1"].parent == "Problème A"
        assert places["Oasis"].parent == ""

    def test_two_nodes_of_a_column_do_not_touch(self):
        places = lay_out(a_board())
        for the_column in {place.x for place in places}:
            heights = sorted(p.y for p in places if p.x == the_column)
            gaps = [b - a for a, b in pairwise(heights)]
            assert all(gap >= BETWEEN_LINES for gap in gaps), the_column

    def test_columns_are_further_apart_than_they_are_wide(self):
        """Un texte de deux lignes déborde de la boîte annoncée."""
        assert BETWEEN_COLUMNS > WIDTH

    def test_a_parent_is_centred_on_its_children(self):
        """Otherwise the board leans upwards at every loaded branch."""
        places = {place.node.text: place for place in lay_out(a_board())}
        children = [places["Piste A1"].y, places["Piste A2"].y]
        assert places["Problème A"].y == sum(children) / 2

    def test_a_board_of_one_node_holds(self):
        places = lay_out(Board("Oasis"))
        assert len(places) == 1 and places[0].x == 0 and places[0].y == 0


class TestWhateverTheTree:
    @given(trees())
    def test_every_node_has_a_place_and_no_two_of_a_column_touch(self, root):
        places = lay_out(a_board_grown_into(root))
        assert len(places) == root.count()
        for the_column in {place.x for place in places}:
            heights = sorted(p.y for p in places if p.x == the_column)
            gaps = [b - a for a, b in pairwise(heights)]
            assert all(gap >= BETWEEN_LINES for gap in gaps), the_column

    @given(trees())
    def test_a_parent_sits_one_column_left_between_its_first_and_last_child(self, root):
        places = {id(place.node): place for place in lay_out(a_board_grown_into(root))}

        def check(node: Node) -> None:
            if not node.children:
                return
            mine = places[id(node)]
            first, last = places[id(node.children[0])], places[id(node.children[-1])]
            assert first.y <= mine.y <= last.y
            for child in node.children:
                assert places[id(child)].x == mine.x + BETWEEN_COLUMNS
                assert places[id(child)].parent == node.text
                check(child)

        check(root)
