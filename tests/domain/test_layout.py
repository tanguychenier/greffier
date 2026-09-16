"""Laying out a tree so that nothing overlaps."""

from greffier.domain.board import Board, Contribution, join
from greffier.domain.layout import (
    BETWEEN_COLUMNS,
    BETWEEN_LINES,
    WIDTH,
    lay_out,
)


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
            gaps = [b - a for a, b in zip(heights, heights[1:], strict=False)]
            assert all(gap >= BETWEEN_LINES for gap in gaps), the_column

    def test_columns_are_further_apart_than_they_are_wide(self):
        """Un texte de deux lignes déborde de la boîte annoncée."""
        assert BETWEEN_COLUMNS > WIDTH

    def test_a_parent_is_centred_on_its_children(self):
        """Sinon la carte penche vers le haut à chaque branche chargée."""
        places = {place.node.text: place for place in lay_out(a_board())}
        children = [places["Piste A1"].y, places["Piste A2"].y]
        assert places["Problème A"].y == sum(children) / 2

    def test_a_board_of_one_node_holds(self):
        places = lay_out(Board("Oasis"))
        assert len(places) == 1 and places[0].x == 0 and places[0].y == 0
