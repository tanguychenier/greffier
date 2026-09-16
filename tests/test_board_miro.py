"""Writing a board to Miro: what is refused before any call at all."""

import pytest

from greffier.adapters import board_miro
from greffier.adapters.board_miro import FORBIDDEN, MiroRefused, token


class TestForbiddenBoards:
    """A board documenting a signature workflow does not belong to the tool.

    Writing to it was explicitly forbidden, and the question has already been asked
    once by its author. So it lives in the code, not in a piece of guidance.
    """

    def test_the_forbidden_list_is_not_empty(self):
        assert FORBIDDEN

    def test_publishing_to_a_forbidden_board_fails_before_any_call(self, monkeypatch):
        def never(*_args, **_options):
            raise AssertionError("aucun appel ne doit partir")

        monkeypatch.setattr(board_miro, "_call", never)
        with pytest.raises(MiroRefused, match="interdits"):
            board_miro.texts_present(next(iter(FORBIDDEN)))


class TestWhereTheTokenComesFrom:
    def test_the_environment_is_read_first(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "abc")
        assert token() == "abc"

    def test_a_file_may_carry_it(self, monkeypatch, tmp_path):
        file = tmp_path / "jeton.txt"
        file.write_text("depuis-le-fichier\n", encoding="utf-8")
        monkeypatch.delenv("GREFFIER_MIRO_JETON", raising=False)
        monkeypatch.setenv("GREFFIER_MIRO_JETON_FICHIER", str(file))
        assert token() == "depuis-le-fichier"

    def test_with_no_token_the_message_says_what_to_do(self, monkeypatch):
        monkeypatch.delenv("GREFFIER_MIRO_JETON", raising=False)
        monkeypatch.delenv("GREFFIER_MIRO_JETON_FICHIER", raising=False)
        with pytest.raises(MiroRefused, match="GREFFIER_MIRO_JETON"):
            token()

    def test_no_path_is_hard_coded(self):
        """A public tool does not go looking inside one project's folder."""
        from pathlib import Path

        source = Path(board_miro.__file__).read_text(encoding="utf-8")
        assert "cidr" not in source.lower()
        assert "/var/miro" not in source


class TestPublishingWithoutNetwork:
    def mark(self, monkeypatch, present_line=(), poses=None):
        """Replaces the API with a stand-in that writes down what it is asked."""
        calls = []

        def wrong(path, http_method="GET", corps=None):
            calls.append((http_method, path, corps))
            if "/items" in path:
                return {"data": [
                    {"data": {"content": f"<p>{text}</p>"}} for text in present_line
                ]}
            return {"id": f"objet-{len(calls)}"}

        monkeypatch.setattr(board_miro, "_call", wrong)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return calls

    def test_only_the_missing_nodes_are_placed(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Déjà là"), Contribution("Nouveau")])
        self.mark(monkeypatch, present_line=("Oasis", "Déjà là"))
        written = board_miro.publish(board, "uXjVtest=")
        assert written.poses == ("Nouveau",)
        assert set(written.already) == {"Oasis", "Déjà là"}

    def test_nothing_is_deleted_or_changed(self, monkeypatch):
        """What somebody put there stays as it is."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Un point")])
        calls = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        methods = {http_method for http_method, _, _ in calls}
        assert methods <= {"GET", "POST"}, "ni DELETE ni PATCH"

    def test_the_standing_is_read_from_the_colour(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, Kind, Standing, join

        board = Board("Oasis")
        # A lead: only a lead and an action can be settled.
        join(board, [Contribution("Décidé", kind=Kind.LEAD, state=Standing.AGREED)])
        calls = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        colours = [
            corps["style"]["fillColor"]
            for http_method, path, corps in calls
            if http_method == "POST" and "sticky_notes" in path and corps
        ]
        assert board_miro.COLOURS[Standing.AGREED] in colours

    def test_the_text_is_escaped(self, monkeypatch):
        """A "<" in a label must not break the HTML content."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("a < b & c")])
        calls = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        contents = [
            corps["data"]["content"]
            for http_method, path, corps in calls
            if http_method == "POST" and "sticky_notes" in path and corps
        ]
        assert any("&lt;" in content and "&amp;" in content for content in contents)


class TestTheLinksBetweenNodes:
    """A board without a single line was published with nothing to say so."""

    def mark(self, monkeypatch):
        calls = []

        def wrong(path, http_method="GET", corps=None):
            calls.append((http_method, path, corps))
            if "/items" in path:
                return {"data": []}
            return {"id": "3458764683144805305"}

        monkeypatch.setattr(board_miro, "_call", wrong)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return calls

    def test_the_identifiers_leave_as_numbers(self):
        """L'API les refuse en chaînes : « expected of type [Number] »."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Un point")])
        calls = []

        def wrong(path, http_method="GET", corps=None):
            calls.append((http_method, path, corps))
            if "/items" in path:
                return {"data": []}
            return {"id": "3458764683144805305"}

        import pytest as _pytest
        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(board_miro, "_call", wrong)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        try:
            board_miro.publish(board, "uXjVtest=")
        finally:
            monkeypatch.undo()
        liens = [corps for http_method, path, corps in calls
                 if "connectors" in path and corps]
        assert liens, "un lien doit être tracé"
        assert isinstance(liens[0]["startItem"]["id"], int)

    def test_the_links_drawn_are_counted(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("A"), Contribution("B")])
        self.mark(monkeypatch)
        written = board_miro.publish(board, "uXjVtest=")
        assert written.liens == 2
        assert written.links_missed == 0

    def test_the_links_that_failed_are_counted_not_swallowed(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("A")])

        def wrong(path, http_method="GET", corps=None):
            if "/items" in path:
                return {"data": []}
            if "connectors" in path:
                raise board_miro.MiroRefused("refusé")
            return {"id": "3458764683144805305"}

        monkeypatch.setattr(board_miro, "_call", wrong)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        written = board_miro.publish(board, "uXjVtest=")
        assert written.liens == 0
        assert written.links_missed == 1, "l'échec doit se compter"


class TestLaRacine:
    def test_the_subject_carries_no_standing(self):
        """"Oasis : en discussion" would say the subject itself is under debate."""
        from greffier.domain.board import Board

        board = Board("Oasis")
        assert board.root is not None
        html = board_miro._as_html(board.root, "")
        assert "en discussion" not in html

    def test_the_subject_has_its_own_colour(self):
        from greffier.domain.board import Kind

        assert Kind.SUBJECT in __import__(
            "greffier.domain.board", fromlist=["SANS_ETAT"]
        ).WITHOUT_STANDING
