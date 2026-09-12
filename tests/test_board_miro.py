"""Writing a board to Miro: what is refused before any call at all."""

import pytest

from greffier.adapters import board_miro
from greffier.adapters.board_miro import INTERDITS, MiroRefused, token


class TestForbiddenBoards:
    """A board documenting a signature workflow does not belong to the tool.

    Writing to it was explicitly forbidden, and the question has already been asked
    once by its author. So it lives in the code, not in a piece of guidance.
    """

    def test_the_forbidden_list_is_not_empty(self):
        assert INTERDITS

    def test_publishing_to_a_forbidden_board_fails_before_any_call(self, monkeypatch):
        def jamais(*_args, **_options):
            raise AssertionError("aucun appel ne doit partir")

        monkeypatch.setattr(board_miro, "_appeler", jamais)
        with pytest.raises(MiroRefused, match="interdits"):
            board_miro.textes_presents(next(iter(INTERDITS)))


class TestWhereTheTokenComesFrom:
    def test_l_environnement_est_lu_d_abord(self, monkeypatch):
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


class TestPublicationSansReseau:
    def mark(self, monkeypatch, present_line=(), poses=None):
        """Remplace l'API par une doublure qui note ce qu'on lui demande."""
        appels = []

        def faux(path, methode="GET", corps=None):
            appels.append((methode, path, corps))
            if "/items" in path:
                return {"data": [
                    {"data": {"content": f"<p>{text}</p>"}} for text in present_line
                ]}
            return {"id": f"objet-{len(appels)}"}

        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return appels

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
        appels = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        methodes = {methode for methode, _, _ in appels}
        assert methodes <= {"GET", "POST"}, "ni DELETE ni PATCH"

    def test_the_standing_is_read_from_the_colour(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, Kind, Standing, join

        board = Board("Oasis")
        # Une piste : seuls une piste et une action peuvent être actées.
        join(board, [Contribution("Décidé", kind=Kind.LEAD, state=Standing.AGREED)])
        appels = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        colours = [
            corps["style"]["fillColor"]
            for methode, path, corps in appels
            if methode == "POST" and "sticky_notes" in path and corps
        ]
        assert board_miro.COLOURS[Standing.AGREED] in colours

    def test_the_text_is_escaped(self, monkeypatch):
        """A "<" in a label must not break the HTML content."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("a < b & c")])
        appels = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        contenus = [
            corps["data"]["content"]
            for methode, path, corps in appels
            if methode == "POST" and "sticky_notes" in path and corps
        ]
        assert any("&lt;" in content and "&amp;" in content for content in contenus)


class TestTheLinksBetweenNodes:
    """A board without a single line was published with nothing to say so."""

    def mark(self, monkeypatch):
        appels = []

        def faux(path, methode="GET", corps=None):
            appels.append((methode, path, corps))
            if "/items" in path:
                return {"data": []}
            return {"id": "3458764683144805305"}

        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return appels

    def test_les_identifiants_partent_en_nombres(self):
        """L'API les refuse en chaînes : « expected of type [Number] »."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Un point")])
        appels = []

        def faux(path, methode="GET", corps=None):
            appels.append((methode, path, corps))
            if "/items" in path:
                return {"data": []}
            return {"id": "3458764683144805305"}

        import pytest as _pytest
        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        try:
            board_miro.publish(board, "uXjVtest=")
        finally:
            monkeypatch.undo()
        liens = [corps for methode, path, corps in appels
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
        assert written.liens_manques == 0

    def test_the_links_that_failed_are_counted_not_swallowed(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("A")])

        def faux(path, methode="GET", corps=None):
            if "/items" in path:
                return {"data": []}
            if "connectors" in path:
                raise board_miro.MiroRefused("refusé")
            return {"id": "3458764683144805305"}

        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        written = board_miro.publish(board, "uXjVtest=")
        assert written.liens == 0
        assert written.liens_manques == 1, "l'échec doit se compter"


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
