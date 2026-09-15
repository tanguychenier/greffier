"""What a box does when there is nobody to answer it.

These tests never open one: they check the door in front of them. A box opened
here would wait for a click that no test can produce, and the suite would hang
rather than fail, which is the whole reason `asking.py` exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

from greffier.interface import asking

WINDOW = Path(__file__).resolve().parents[2] / "src" / "greffier" / "interface" / "window.py"


class TestWhetherAnybodyIsThere:
    def test_the_test_screen_means_nobody(self, monkeypatch) -> None:
        monkeypatch.setenv(asking.TEST_SCREEN, "1")
        assert not asking.somebody_is_there()

    def test_without_it_a_person_is_assumed(self, monkeypatch) -> None:
        monkeypatch.delenv(asking.TEST_SCREEN, raising=False)
        assert asking.somebody_is_there()


class TestAnsweringForNobody:
    def test_a_question_is_answered_no(self, monkeypatch) -> None:
        # No, never yes: each of these guards something that costs -- a
        # gigabyte fetched, a mail sent, a recording erased.
        monkeypatch.setenv(asking.TEST_SCREEN, "1")
        asking.forget_what_was_asked()
        assert asking.ask_yes_no("Greffier", "Effacer définitivement ?") is False

    def test_what_would_have_been_shown_is_kept(self, monkeypatch) -> None:
        monkeypatch.setenv(asking.TEST_SCREEN, "1")
        asking.forget_what_was_asked()
        asking.ask_yes_no("Greffier", "Télécharger 1,5 Go ?")
        asking.tell("Greffier", "C'est fait.")
        asking.warn("Greffier", "Ça sent le roussi.")
        asking.complain("Greffier", "Raté.")
        assert asking.unanswered() == [
            "Télécharger 1,5 Go ?", "C'est fait.", "Ça sent le roussi.", "Raté.",
        ]

    def test_one_test_does_not_read_another_s_questions(self, monkeypatch) -> None:
        monkeypatch.setenv(asking.TEST_SCREEN, "1")
        asking.tell("Greffier", "d'avant")
        asking.forget_what_was_asked()
        assert asking.unanswered() == []


class TestNoBoxEscapesThisModule:
    def test_the_window_never_opens_one_itself(self) -> None:
        # A single `messagebox.showinfo` or `filedialog.askopenfilenames` left
        # in the window is a window that can hang on a screen with nobody in
        # front of it, and the suite would stop dead rather than say why.
        arbre = ast.parse(WINDOW.read_text(encoding="utf-8"))
        appels = [
            node for node in ast.walk(arbre)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in ("messagebox", "filedialog")
        ]
        assert appels == [], f"{len(appels)} boîte(s) hors de asking.py"


class TestPickingAFileIsABoxToo:
    def test_nothing_is_taken_in_where_nobody_can_choose(self, monkeypatch) -> None:
        monkeypatch.setenv(asking.TEST_SCREEN, "1")
        asking.forget_what_was_asked()
        assert asking.files_to_open("Déposer des enregistrements") == ()
        assert asking.unanswered() == ["Déposer des enregistrements"]

    def test_nothing_is_written_where_nobody_can_choose(self, monkeypatch) -> None:
        monkeypatch.setenv(asking.TEST_SCREEN, "1")
        asking.forget_what_was_asked()
        assert asking.where_to_save(
            "Exporter la transcription",
            initialfile="reunion.srt",
            filetypes=(("Sous-titres SRT", "*.srt"),),
        ) == ""
        assert asking.unanswered() == ["Exporter la transcription"]
