"""The real window, built and painted, rather than what it computes.

`test_window.py` covers what the window works out before showing anything. It
cannot see what these tests see: that the window opens at all, that it opens
**before** it asks anything, and that every tab paints. The fixture for this
existed and no test used it, which is how a modal box came to be opened from
`__init__` -- on a machine with no models, the first thing Greffier did was ask
for a gigabyte and a half over an empty grey rectangle, and the proof of the
window hung there instead of photographing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from greffier.interface import asking

TABS = ("Préparation", "Réunions", "En direct", "Voix", "Conversation", "Réglages")


class TestOpeningBeforeAsking:
    def test_building_the_window_asks_nothing(self, test_screen) -> None:
        # The question about the missing models is owed -- this machine has
        # none -- and it is owed *after* there is a window behind it.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        built = Window(Config())
        try:
            assert asking.unanswered() == []
            assert built.root.winfo_exists()
        finally:
            built.root.destroy()

    def test_the_question_comes_once_the_window_is_painted(self, test_screen) -> None:
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        built = Window(Config())
        try:
            asked: list[str] = []
            for _ in range(20):
                built.root.update()
                asked = asking.unanswered()
                if asked:
                    break
                built.root.after(100)
                built.root.update()
            assert asked, "la proposition des modèles n'est jamais venue"
            # Compared against the catalogue and not against French words: the
            # window speaks the language of the machine, and the continuous
            # integration runner speaks English.
            template = built.says("modeles.manquants", weight="0 Mo")
            start = template.split("0 Mo")[0][:40]
            assert any(question.startswith(start) for question in asked)
        finally:
            built.root.destroy()

    def test_the_question_waits_for_the_window_to_be_seen(self, test_screen, monkeypatch) -> None:
        """On Windows, idle came before the window was on screen: the question
        stood alone on the desktop. It now waits until the window is viewable."""
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        seen_when_asked: list[bool] = []
        original = Window._offer_the_models

        def noting(self) -> None:
            seen_when_asked.append(bool(self.root.winfo_viewable()))
            original(self)

        monkeypatch.setattr(Window, "_offer_the_models", noting)
        built = Window(Config())
        try:
            built.root.withdraw()
            built.root.update()
            assert seen_when_asked == [], "posée sur une fenêtre retirée de l'écran"
            built.root.deiconify()
            for _ in range(20):
                built.root.update()
                if seen_when_asked:
                    break
                built.root.after(100)
                built.root.update()
            assert seen_when_asked == [True]
        finally:
            built.root.destroy()

    def test_a_window_that_never_shows_still_gets_its_question(
        self, test_screen, monkeypatch
    ) -> None:
        from greffier.adapters.configuration import Config
        from greffier.interface import window as module
        from greffier.interface.window import Window

        monkeypatch.setattr(module, "PATIENCE_BEFORE_ASKING", 2)
        built = Window(Config())
        try:
            built.root.withdraw()
            for _ in range(6):
                built.root.update()
                built.root.after(120)
                built.root.update()
            assert asking.unanswered()
        finally:
            built.root.destroy()

    def test_nothing_is_fetched_when_nobody_answered(self, test_screen) -> None:
        # No answer means no: a gigabyte and a half is not something to start
        # on a machine where nobody said yes.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        built = Window(Config())
        try:
            built.root.update()
            assert built.jobs == []
        finally:
            built.root.destroy()


class TestEveryTabPaints:
    def test_the_six_tabs_are_there(self, window) -> None:
        assert tuple(window.tabs._pages) == TABS

    @pytest.mark.parametrize("caption", TABS)
    def test_a_tab_paints_and_holds_something(self, window, caption: str) -> None:
        window.tabs.reveal(caption)
        window.root.update()
        page = window.tabs._pages[caption]
        assert page.winfo_children(), f"l'onglet « {caption} » est vide"

    def test_switching_tabs_does_not_resize_the_window(self, window) -> None:
        # The window changed size on every tab switch until `geometry()` was
        # set once and for all; nothing must bring that back.
        window.root.update()
        width, height = window.root.winfo_width(), window.root.winfo_height()
        for caption in TABS:
            window.tabs.reveal(caption)
            window.root.update()
        assert (window.root.winfo_width(), window.root.winfo_height()) == (width, height)


class TestWhatTheWindowShowsWithNothingYet:
    def test_it_says_it_is_ready_rather_than_nothing(self, window) -> None:
        window.root.update()
        assert window.title.cget("text") == window.says("fenetre.pret")

    def test_the_status_line_starts_empty(self, window) -> None:
        assert window.status_line.cget("text") == ""


class TestNoButtonIsSqueezedOutOfShape:
    """At its narrowest, the window must still hold everything it draws.

    Two buttons have already been lost this way. The seventh of the Réunions
    tab sat outside the frame; « Séparer les deux voix » was subtler and worse:
    Tk did not push it out, it **squeezed** it, handing 130 px to a button that
    asked for 190 and cutting its last word off. Nothing raises, nothing moves,
    the label is simply wrong. Measured at 880 px, the smallest size the window
    itself declares.
    """

    @staticmethod
    def _squeezed(page) -> list[str]:
        from greffier.interface.appearance import Button

        narrow = []

        def walk(widget) -> None:
            for child in widget.winfo_children():
                if (isinstance(child, Button) and child.winfo_ismapped()
                        and child.winfo_width() < child.winfo_reqwidth()):
                    narrow.append(
                        f"{child.winfo_width()} px pour "
                        f"{child.winfo_reqwidth()} demandés"
                    )
                walk(child)

        walk(page)
        return narrow

    @pytest.mark.parametrize("caption", TABS)
    def test_at_its_narrowest_no_button_is_cut(self, window, caption: str) -> None:
        window.root.geometry("880x660")
        window.tabs.reveal(caption)
        window.root.update()
        window.root.update()
        assert self._squeezed(window.tabs._pages[caption]) == []


class TestForgettingSomebodyIsReachable:
    def test_the_voices_tab_offers_it(self, window) -> None:
        window.tabs.reveal("Voix")
        window.root.update()
        assert window.forget_button.winfo_ismapped()

    def test_it_aims_at_the_first_name_that_was_typed(self, window) -> None:
        window.name_field.insert(0, "  Élodie  ")
        assert window._person_aimed_at() == "Élodie"

    def test_with_nothing_typed_and_nothing_chosen_it_aims_at_nobody(
        self, window
    ) -> None:
        assert window._person_aimed_at() == ""

    def test_it_says_so_rather_than_erasing_at_random(self, window) -> None:
        from greffier.interface import asking

        asking.forget_what_was_asked()
        window._forget_a_person()
        assert any("prénom" in said for said in asking.unanswered())


class TestExportingFromTheWindow:
    def test_the_meetings_tab_offers_it(self, window) -> None:
        window.tabs.reveal("Réunions")
        window.root.update()
        headings = [
            button.itemcget(button._text, "text")
            for button in window.meeting_buttons
        ]
        assert "Exporter…" in headings

    def test_with_no_meeting_chosen_it_says_so_rather_than_writing(
        self, window
    ) -> None:
        window._export_selection()
        assert window.status_line.cget("text") == window.says(
            "reunions.choisis_une_reunion"
        )


class TestWhatAProcessedMeetingTellsOnScreen:
    """Read off the chain's own Outcome, not off a stand-in.

    The window used to read `avertissements` and `voix_significatives` on an
    object whose fields had been renamed in English: every warning of the chain
    went unshown, and the offer to name the voices never came.
    """

    def test_the_chain_s_warnings_are_said_in_the_thread(self, window) -> None:
        from greffier.application.process import Outcome

        outcome = Outcome(audio=Path("/tmp/2026-09-15_10h00_reunion.wav"))
        outcome.warnings.append("Ton micro est resté muet : seuls les autres sont transcrits.")
        window._processing_done(outcome.audio, outcome, None)
        window.root.update()
        assert "Ton micro est resté muet" in window.thread.get("1.0", "end")

    def test_voices_without_a_name_are_offered_for_naming(self, window) -> None:
        from greffier.application.process import Outcome
        from greffier.domain.models import Span, SpeakerTurn

        outcome = Outcome(audio=Path("/tmp/2026-09-15_10h00_reunion.wav"))
        outcome.turns = [SpeakerTurn(Span(0, 40), "1"), SpeakerTurn(Span(40, 90), "2")]
        outcome.names = {"1": "Josiane"}
        window._processing_done(outcome.audio, outcome, None)
        window.root.update()
        assert "1 voix ne portent pas encore de nom" in window.thread.get("1.0", "end")


class TestTheBadgeOnTheConversationTab:
    """The badge counts what has not been looked at, not everything pending.

    Reported in use: read a question, switch tab, one more arrives, and the
    badge said three where one was new.
    """

    @staticmethod
    def _ask(window, numbers: list[int]) -> None:
        from greffier.adapters import questions_file
        from greffier.domain.questions import Question, Reason

        window._thread_meeting = "2026-09-16_10h00_reunion"
        file = questions_file.questions_file(
            window.config.paths.questions, window._thread_meeting
        )
        for number in numbers:
            questions_file.publish(
                file, Question(number=number, text=f"question {number}", motif=Reason.NEAR_TERM)
            )
        window._follow_the_questions()
        window.root.update()

    @staticmethod
    def _badge(window) -> int:
        return window.tabs._segments["Conversation"]._count

    def test_questions_arriving_while_another_tab_is_open_are_counted(self, window) -> None:
        window.tabs.reveal("Préparation")
        self._ask(window, [1, 2])
        assert self._badge(window) == 2

    def test_opening_the_tab_clears_the_badge(self, window) -> None:
        window.tabs.reveal("Préparation")
        self._ask(window, [1, 2])
        window.tabs.reveal("Conversation")
        window.root.update()
        assert self._badge(window) == 0

    def test_one_more_question_after_a_look_counts_one_not_three(self, window) -> None:
        window.tabs.reveal("Préparation")
        self._ask(window, [1, 2])
        window.tabs.reveal("Conversation")
        window.root.update()
        window.tabs.reveal("Préparation")
        self._ask(window, [3])
        assert self._badge(window) == 1

    def test_a_question_arriving_on_the_open_tab_is_already_seen(self, window) -> None:
        window.tabs.reveal("Conversation")
        self._ask(window, [1])
        window.tabs.reveal("Préparation")
        window.root.update()
        assert self._badge(window) == 0


class TestATokenPastedIntoTheWindow:
    """The assistant says it has no access to a source without a token and
    asks for it. This is where it goes, without a terminal."""

    @staticmethod
    def _registry(config) -> None:
        config.paths.sources.parent.mkdir(parents=True, exist_ok=True)
        config.paths.sources.write_text(
            '[[sources]]\nnom = "recherche"\ngenre = "gitlab"\n'
            'adresse = "https://gitlab.example.fr"\nprojet = "equipe/outil"\n'
            'jeton = "GREFFIER_JETON_DE_LA_FENETRE"\n',
            encoding="utf-8",
        )

    def test_with_no_registry_the_block_says_so(self, window):
        assert window.sources_word.cget("text") == window.says("reglages.sources_aucune")

    def test_a_source_without_a_token_is_named_as_such(self, test_screen, monkeypatch):
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        monkeypatch.delenv("GREFFIER_JETON_DE_LA_FENETRE", raising=False)
        config = Config()
        self._registry(config)
        opened = Window(config)
        try:
            assert opened.sources_word.cget("text") == opened.says(
                "reglages.source_jeton_absent",
                source="recherche, gitlab equipe/outil sur https://gitlab.example.fr (lecture)",
            )
            assert opened.source_setting.value() == "recherche"
        finally:
            opened.root.destroy()

    def test_the_token_pasted_is_stored_and_the_line_changes(self, test_screen, monkeypatch):
        from greffier.adapters import sources_file
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        monkeypatch.delenv("GREFFIER_JETON_DE_LA_FENETRE", raising=False)
        config = Config()
        self._registry(config)
        opened = Window(config)
        try:
            opened.token_field.insert(0, "glpat-colle-dans-la-fenetre")
            opened._store_the_token()
            assert sources_file.stored_tokens(sources_file.tokens_file()) == {
                "GREFFIER_JETON_DE_LA_FENETRE": "glpat-colle-dans-la-fenetre"
            }
            assert opened.sources_word.cget("text") == opened.says(
                "reglages.source_jeton_present",
                source="recherche, gitlab equipe/outil sur https://gitlab.example.fr (lecture)",
            )
            assert opened.token_field.get() == "", "the secret does not stay on screen"
            assert opened.settings_word.cget("text") == opened.says(
                "reglages.jeton_depose", source="recherche"
            )
        finally:
            opened.root.destroy()

    def test_the_assistant_reads_the_source_from_the_next_question(
        self, test_screen, monkeypatch
    ):
        """The Conversation tab keeps a reading of the sources: it is dropped."""
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window

        monkeypatch.delenv("GREFFIER_JETON_DE_LA_FENETRE", raising=False)
        config = Config()
        self._registry(config)
        opened = Window(config)
        try:
            assert "aucun jeton disponible" in opened._with_the_documents("", "x")
            opened.token_field.insert(0, "glpat-colle")
            opened._store_the_token()
            assert opened._sources is None
        finally:
            opened.root.destroy()


def _a_kept_meeting(window, name="2026-09-12_10h00_recette"):
    """Written by the store the window reads, the shape the tool writes."""
    from datetime import UTC, datetime

    from greffier.domain.meeting import StoredMeeting
    from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

    window.store.record(StoredMeeting(
        identifier=name,
        audio=window.config.paths.recordings / f"{name}.wav",
        processed_at=datetime.now(UTC),
        duration=42.0,
        utterances=[Utterance(span=Span(0.0, 4.0), text="On décale la recette à jeudi.",
                              voice="1"),
                    Utterance(span=Span(4.0, 8.0), text="Maud relance le partenaire lundi.",
                              voice="2")],
        turns=[SpeakerTurn(voice="1", span=Span(0.0, 4.0), source=Source.MIC),
               SpeakerTurn(voice="2", span=Span(4.0, 8.0), source=Source.MIC)],
        names={"1": "Jacques"},
        propositions={},
        warnings=[],
    ))
    window._load_meetings()
    window._choose(name)
    window.root.update()
    return name


def _jobs_run_inline(window):
    """A job runs on the spot: Tk refuses `after` from a thread while the main
    loop is not running, which is the case of a window driven by a test."""

    def run(job):
        outcome, trouble = None, None
        try:
            outcome = job.do_it(job.messages.put)
        except Exception as caught:  # noqa: BLE001 - reported as the window would
            trouble = caught
        window._finish(job, outcome, trouble)

    window._run_job = run


class TestTheMeetingsTabOnAKeptMeeting:
    def test_the_meeting_is_listed_with_its_words_and_its_voices(self, window):
        name = _a_kept_meeting(window)
        values = window.listing.item(name)["values"]
        assert values[1] == 1, "one voice still to name"
        assert values[2] == 11, "the words of the two sentences"
        assert values[3] == "non", "no minutes yet"

    def test_renaming_gives_a_subject_and_keeps_the_identifier(self, window, monkeypatch):
        name = _a_kept_meeting(window)
        monkeypatch.setattr("tkinter.simpledialog.askstring", lambda *a, **k: "point recette")
        window._rename_selection()
        window.root.update()
        assert window.store.read(name).subject == "point recette"
        assert window.listing.exists(name)
        assert "Renommée" in window.status_line.cget("text")

    def test_a_rename_given_up_changes_nothing(self, window, monkeypatch):
        name = _a_kept_meeting(window)
        monkeypatch.setattr("tkinter.simpledialog.askstring", lambda *a, **k: None)
        window._rename_selection()
        assert window.store.read(name).subject == ""

    def test_forgetting_erases_the_pieces_once_confirmed(self, window, monkeypatch):
        from greffier.interface import asking

        name = _a_kept_meeting(window)
        monkeypatch.setattr(asking, "ask_yes_no", lambda *a, **k: True)
        window._forget_selection()
        window.root.update()
        assert name not in window.store.list_()
        assert "effacé" in window.status_line.cget("text")

    def test_forgetting_refused_keeps_everything(self, window, monkeypatch):
        from greffier.interface import asking

        name = _a_kept_meeting(window)
        monkeypatch.setattr(asking, "ask_yes_no", lambda *a, **k: False)
        window._forget_selection()
        assert name in window.store.list_()

    def test_exporting_writes_the_shape_the_extension_says(self, window, monkeypatch, tmp_path):
        from greffier.interface import asking

        name = _a_kept_meeting(window)
        target = tmp_path / f"{name}.csv"
        monkeypatch.setattr(asking, "where_to_save", lambda *a, **k: str(target))
        window._export_selection()
        written = target.read_text(encoding="utf-8-sig")
        assert "Jacques" in written and "recette" in written
        assert "2 tour(s) de parole" in window.status_line.cget("text")

    def test_an_unknown_extension_is_refused_by_name(self, window, monkeypatch, tmp_path):
        from greffier.interface import asking

        _a_kept_meeting(window)
        complaints = []
        monkeypatch.setattr(asking, "where_to_save", lambda *a, **k: str(tmp_path / "x.doc"))
        monkeypatch.setattr(asking, "complain", lambda title, text: complaints.append(text))
        window._export_selection()
        assert complaints and "« .doc » n'est pas un format connu" in complaints[0]

    def test_writing_the_minutes_again_uses_the_writer_and_lists_them(self, window, monkeypatch):
        name = _a_kept_meeting(window)

        class Writer:
            def write_up(self, text):
                return "# Compte rendu : recette\n\n## Décisions\n\n- Jeudi.\n"

        monkeypatch.setattr("greffier.wiring.writer", lambda config: Writer())
        _jobs_run_inline(window)
        window._write_up_only(name)
        window.root.update()
        assert (window.config.paths.minutes_folder / f"{name}.md").exists()
        assert window.listing.item(name)["values"][3] == "oui"
        assert window.status_line.cget("text") == window.says("reunions.compte_rendu_pret")

    def test_without_a_writer_the_minutes_are_not_attempted(self, window, monkeypatch):
        from greffier.interface import asking

        name = _a_kept_meeting(window)
        told = []
        monkeypatch.setattr("greffier.wiring.writer", lambda config: None)
        monkeypatch.setattr(asking, "tell", lambda title, text: told.append(text))
        window._write_up_only(name)
        assert told == [window.says("reunions.aucun_redacteur")]
        assert not window.jobs


class TestTheSettingsAreSavedFromTheWindow:
    def test_a_recipient_typed_lands_in_the_settings_file(self, window):
        window.recipient_setting.delete(0, "end")
        window.recipient_setting.insert(0, "maud@example.fr")
        window._save_settings()
        from greffier.adapters.configuration import Config

        assert Config.load(None).minutes.recipient == "maud@example.fr"

    def test_the_live_thread_can_be_switched_off(self, window):
        window.live_active.set(False)
        window._save_settings()
        from greffier.adapters.configuration import Config

        assert Config.load(None).live.active is False


class TestHandingADocumentToTheWindow:
    """From the project manager's seat: "voilà le budget, tu peux me dire…"."""

    def _thread_of(self, window) -> str:
        return window.thread.get("1.0", "end")

    def test_a_document_is_kept_for_the_meeting_and_read_back_to_her(
        self, window, monkeypatch, tmp_path
    ):
        from greffier.adapters import attachments_file
        from greffier.interface import asking

        name = _a_kept_meeting(window)
        note = tmp_path / "budget.md"
        note.write_text("Budget du lot 2 : 42 000 euros hors taxes.\n", encoding="utf-8")
        monkeypatch.setattr(asking, "files_to_open", lambda *a, **k: (str(note),))
        monkeypatch.setattr("greffier.wiring.mapper", lambda config: None)
        _jobs_run_inline(window)
        window._supply_a_document()
        window.root.update()
        kept = attachments_file.list_(window.config.paths.pieces, name)
        assert [p.name for p in kept] == ["budget.md"]
        assert "« budget.md » lu" in self._thread_of(window)
        assert "42 000" in window._with_the_documents("", name)

    def test_what_a_document_teaches_goes_to_the_context_once_accepted(
        self, window, monkeypatch, tmp_path
    ):
        from greffier.adapters import context_file
        from greffier.interface import asking

        _a_kept_meeting(window)
        note = tmp_path / "glossaire.md"
        note.write_text("CASA : le comité d'architecture. Présidé par Maud Riel.\n",
                        encoding="utf-8")

        class Reader:
            own_guidance = ""

            def write_up(self, text):
                return ('```json\n[{"ecriture": "CASA", "sens": "comité d\'architecture", '
                        '"genre": "terme"}, {"ecriture": "Maud Riel", "sens": "présidente", '
                        '"genre": "personne"}]\n```')

        monkeypatch.setattr(asking, "files_to_open", lambda *a, **k: (str(note),))
        monkeypatch.setattr(asking, "ask_yes_no", lambda *a, **k: True)
        monkeypatch.setattr("greffier.wiring.mapper", lambda config: Reader())
        _jobs_run_inline(window)
        window._supply_a_document()
        window.root.update()
        written = window.config.paths.context.read_text(encoding="utf-8")
        assert "CASA" in written and "Maud Riel" in written
        assert "2 entrée(s) ajoutée(s) au contexte" in self._thread_of(window)
        assert context_file.read(window.config.paths.context) is not None

    def test_what_is_refused_stays_out_of_the_context(self, window, monkeypatch, tmp_path):
        from greffier.interface import asking

        _a_kept_meeting(window)
        note = tmp_path / "glossaire.md"
        note.write_text("CASA : le comité d'architecture.\n", encoding="utf-8")

        class Reader:
            own_guidance = ""

            def write_up(self, text):
                return '[{"ecriture": "CASA", "sens": "comité", "genre": "terme"}]'

        monkeypatch.setattr(asking, "files_to_open", lambda *a, **k: (str(note),))
        monkeypatch.setattr(asking, "ask_yes_no", lambda *a, **k: False)
        monkeypatch.setattr("greffier.wiring.mapper", lambda config: Reader())
        _jobs_run_inline(window)
        window._supply_a_document()
        window.root.update()
        assert not window.config.paths.context.exists() or (
            "CASA" not in window.config.paths.context.read_text(encoding="utf-8")
        )
        assert window.says("conversation.rien_ajoute") in self._thread_of(window)

    def test_a_sound_file_is_sent_to_the_meetings_tab_not_read_as_a_document(
        self, window, monkeypatch, tmp_path
    ):
        from greffier.interface import asking

        _a_kept_meeting(window)
        sound = tmp_path / "reunion.wav"
        sound.write_bytes(b"RIFF" + b"\0" * 100)
        monkeypatch.setattr(asking, "files_to_open", lambda *a, **k: (str(sound),))
        window._supply_a_document()
        window.root.update()
        assert "deviennent des réunions à transcrire" in self._thread_of(window)

    def test_nothing_chosen_changes_nothing(self, window, monkeypatch):
        from greffier.interface import asking

        monkeypatch.setattr(asking, "files_to_open", lambda *a, **k: ())
        before = self._thread_of(window)
        window._supply_a_document()
        assert self._thread_of(window) == before


class TestAskingTheWindowAQuestion:
    def _thread_of(self, window) -> str:
        return window.thread.get("1.0", "end")

    def test_without_a_writer_it_says_so(self, window, monkeypatch):
        _a_kept_meeting(window)
        monkeypatch.setattr("greffier.wiring.assistant", lambda config: None)
        window.question.insert(0, "qui relance le partenaire ?")
        window._ask()
        assert window.says("commun.aucun_redacteur_configure") in self._thread_of(window)

    def test_with_no_minutes_yet_it_asks_to_process_first(self, window, monkeypatch):
        _a_kept_meeting(window)

        class Brain:
            def write_up(self, text):
                return "Maud."

        monkeypatch.setattr("greffier.wiring.assistant", lambda config: Brain())
        window.question.insert(0, "qui relance le partenaire ?")
        window._ask()
        assert "n'a pas encore de compte rendu" in self._thread_of(window)

    def test_a_question_on_the_minutes_gets_its_answer_in_the_thread(
        self, window, monkeypatch
    ):
        name = _a_kept_meeting(window)
        minutes = window.config.paths.minutes_folder / f"{name}.md"
        minutes.parent.mkdir(parents=True, exist_ok=True)
        minutes.write_text("# Recette\n\n- Maud relance le partenaire lundi.\n", encoding="utf-8")
        asked = []

        class Brain:
            def write_up(self, text):
                asked.append(text)
                return "C'est Maud, lundi."

        monkeypatch.setattr("greffier.wiring.assistant", lambda config: Brain())
        _jobs_run_inline(window)
        window.question.insert(0, "qui relance le partenaire ?")
        window._ask()
        window.root.update()
        assert "C'est Maud, lundi." in self._thread_of(window)
        assert "qui relance le partenaire ?" in asked[0]
        assert "Maud relance le partenaire lundi" in asked[0], "the minutes are the material"
        assert window.question.get() == ""

    def test_an_empty_question_asks_nothing(self, window, monkeypatch):
        asked = []
        monkeypatch.setattr("greffier.wiring.assistant", lambda config: asked.append(1))
        window.question.delete(0, "end")
        window._ask()
        assert asked == []


class TestTheWindowSaysItDoubtsAtTheMoment:
    """The transcript marked the doubtful passages the next day; the live
    thread now marks them as they appear, while they can be heard again."""

    def _turn(self, window, number, text, confidence):
        from greffier.domain.live import LiveTurn, LiveVoice
        from greffier.domain.models import Span

        window._thread.voice.setdefault("v1", LiveVoice(identifier="v1"))
        turn = LiveTurn(number=number, span=Span(number * 4.0, number * 4.0 + 3.0),
                        text=text, voice="v1", confidence=confidence)
        window._thread.turns.append(turn)
        return turn

    def test_a_doubtful_sentence_carries_the_mark_and_a_sure_one_does_not(self, window):
        from greffier.domain import doubt

        first = self._turn(window, 1, "on cale la recette jeudi", 0.95)
        second = self._turn(window, 2, "le lot deux part en prod", 0.4)
        window._add_to_live([first, second])
        window.root.update()
        shown = window.thread_widget.get("1.0", "end")
        assert f"{doubt.MARK} le lot deux part en prod" in shown
        assert f"{doubt.MARK} on cale" not in shown

    def test_an_unjudged_sentence_is_not_marked(self, window):
        from greffier.domain import doubt

        window._add_to_live([self._turn(window, 1, "bonjour à tous", None)])
        window.root.update()
        assert doubt.MARK not in window.thread_widget.get("1.0", "end")


class TestTheFirstLaunchTakesYouByTheHand:
    """Somebody who has just double-clicked the tool used to see six tabs and
    a question about a gigabyte and a half."""

    def _machine(self, monkeypatch, window, models=False, account=False, mic=False):
        from greffier.adapters import model_files
        from greffier.adapters import system_diagnostic as diagnostic

        class Missing:
            required = True
            role = "transcription"

        monkeypatch.setattr(model_files, "missing",
                            lambda folder, engine: [] if models else [Missing()])
        monkeypatch.setattr(diagnostic, "claude_installed", lambda: account)
        monkeypatch.setattr(diagnostic, "claude_account", lambda: object() if account else None)
        monkeypatch.setattr(window, "_settable_mics",
                            lambda: (("", "Automatique"),) + ((("usb", "Jabra"),) if mic else ()))

    def _shown(self, window) -> str:
        return window.thread.get("1.0", "end")

    def test_with_nothing_done_the_three_steps_are_listed_in_order(self, window, monkeypatch):
        self._machine(monkeypatch, window)
        window._take_by_the_hand()
        shown = self._shown(window)
        assert window.says("premier_lancement.titre") in shown
        for key in ("modeles_a_faire", "compte_a_faire", "micro_a_faire"):
            assert window.says(f"premier_lancement.{key}") in shown
        assert shown.index("modeles" if "modeles" in shown else "models") < shown.index(
            window.says("premier_lancement.compte_a_faire")
        )

    def test_what_is_done_is_ticked(self, window, monkeypatch):
        self._machine(monkeypatch, window, models=True, mic=True)
        window._take_by_the_hand()
        shown = self._shown(window)
        assert window.says("premier_lancement.modeles_fait") in shown
        assert window.says("premier_lancement.compte_a_faire") in shown
        assert window.says("premier_lancement.micro_fait") in shown

    def test_the_same_state_is_said_once(self, window, monkeypatch):
        self._machine(monkeypatch, window)
        window._take_by_the_hand()
        window._take_by_the_hand()
        assert self._shown(window).count(window.says("premier_lancement.titre")) == 1

    def test_once_everything_is_done_it_says_so_and_goes_quiet(self, window, monkeypatch):
        self._machine(monkeypatch, window)
        window._take_by_the_hand()
        self._machine(monkeypatch, window, models=True, account=True, mic=True)
        window._take_by_the_hand()
        shown = self._shown(window)
        assert window.says("premier_lancement.tout_en_place") in shown
        window._take_by_the_hand()
        assert self._shown(window).count(window.says("premier_lancement.tout_en_place")) == 1

    def test_a_machine_with_everything_from_the_start_hears_nothing(self, window, monkeypatch):
        self._machine(monkeypatch, window, models=True, account=True, mic=True)
        window._take_by_the_hand()
        shown = self._shown(window)
        assert window.says("premier_lancement.titre") not in shown
        assert window.says("premier_lancement.tout_en_place") not in shown
