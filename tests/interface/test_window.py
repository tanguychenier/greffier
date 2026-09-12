"""What the window computes before showing anything, covered with no screen.

What touches Tk is not tested here: Tk does not start on a continuous
integration runner. What can be tested is what the window computes before
showing, and that is precisely where the misreadings happen.
"""

from __future__ import annotations

from pathlib import Path

from greffier.interface.readable import button_grid as _grille
from greffier.interface.readable import clock as _clock
from greffier.interface.readable import dot_marker as _marque
from greffier.interface.readable import live_state_line as _live_state_line
from greffier.interface.readable import readable_subject as _readable_subject


class TestTheClock:
    def test_under_an_hour_it_shows_minutes_and_seconds(self) -> None:
        assert _clock(0) == "0:00"
        assert _clock(65) == "1:05"
        assert _clock(3599) == "59:59"

    def test_past_an_hour_the_hours_are_added(self) -> None:
        assert _clock(3600) == "1:00:00"
        assert _clock(3725) == "1:02:05"

    def test_a_negative_length_produces_nothing_monstrous(self) -> None:
        # The length is computed by taking the paused time out: an inconsistent
        # state must not show "-1:-1" in large type in the middle of the window.
        assert _clock(-5).startswith("0:") or _clock(-5) == "0:00"


class TestASubjectAPersonCanRead:
    def test_the_title_of_the_minutes_replaces_the_timestamp(self, tmp_path: Path) -> None:
        # « 2026-08-25_14h33_reunion » ne dit rien de ce qui s'est passé.
        minutes = tmp_path / "cr.md"
        minutes.write_text("# Compte rendu : bug photos et signature Fast\n")
        assert _readable_subject("2026-08-25_14h33_reunion", minutes) == (
            "bug photos et signature Fast"
        )

    def test_with_no_minutes_the_identifier_stays(self, tmp_path: Path) -> None:
        assert _readable_subject("2026-08-25_14h33_x", tmp_path / "absent.md") == (
            "2026-08-25_14h33_x"
        )

    def test_a_title_with_no_colon_is_kept_whole(self, tmp_path: Path) -> None:
        minutes = tmp_path / "cr.md"
        minutes.write_text("# Point hebdomadaire\n")
        assert _readable_subject("id", minutes) == "Point hebdomadaire"

    def test_minutes_with_no_title_leave_the_identifier(self, tmp_path: Path) -> None:
        minutes = tmp_path / "cr.md"
        minutes.write_text("Du texte, mais pas de titre.\n")
        assert _readable_subject("mon-id", minutes) == "mon-id"

    def test_a_title_of_nothing_but_a_colon_does_not_empty_the_column(
        self, tmp_path: Path
    ) -> None:
        minutes = tmp_path / "cr.md"
        minutes.write_text("# Compte rendu :\n")
        assert _readable_subject("mon-id", minutes) == "Compte rendu :"


class TestWhatTheLiveTabSays:
    """What the thread tab says when it has nothing to show.

    An empty tab reads as "nobody is speaking" when it often means "nothing is
    listening": a missing model, a process never started. The difference is
    between waiting and losing your meeting.
    """

    def test_outside_a_meeting_it_explains_what_the_tab_is_for(self) -> None:
        said = _live_state_line(in_a_meeting=False, annonce="", sentences=0)
        assert "Aucune réunion en cours" in said

    def test_a_missing_model_is_named_rather_than_shown_as_a_blank(self) -> None:
        said = _live_state_line(
            in_a_meeting=True, annonce="Aucun modèle de transcription : le fil restera vide.",
            sentences=0,
        )
        assert "Aucun modèle" in said

    def test_before_the_first_slice_it_says_it_is_waiting(self) -> None:
        assert "attente" in _live_state_line(in_a_meeting=True, annonce="", sentences=0)

    def test_as_soon_as_there_is_text_it_says_how_to_correct(self) -> None:
        said = _live_state_line(in_a_meeting=True, annonce="", sentences=14)
        assert "14 phrase(s)" in said
        assert "corriger" in said


class TestTheBadgeOnATab:
    """The count put on a tab nobody is looking at.

    Asked for in use, on the model of a shop's basket: one has to know there is
    something to see without being on the tab, and without a window popping up in
    the middle of a meeting.
    """

    def test_nothing_to_report_draws_nothing(self) -> None:
        assert _marque(0) == ""
        assert _marque(-1) == ""

    def test_the_count_shows_as_it_is(self) -> None:
        assert _marque(1) == "1"
        assert _marque(9) == "9"

    def test_past_nine_the_exact_number_helps_nobody(self) -> None:
        """Deux chiffres déborderaient du disque, et « beaucoup » suffit."""
        assert _marque(10) == "9+"
        assert _marque(42) == "9+"


class TestTheRowOfButtons:
    """The seventh button of the Meetings tab fell outside the window.

    Invisible and unreachable, the very defect the appearance module warns about
    at the top of its file, concerning a button pushed out of the frame. Then,
    once it wrapped, the spread was wrong: five buttons against two, and edges
    that did not line up.
    """

    #: Les largeurs demandées dans l'onglet Réunions, dans l'ordre.
    #: « Envoyer par courriel » vaut 180 : le libellé complet, parce que
    #: « Envoyer » seul ne dit pas ce qui est envoyé.
    MEETINGS = [100, 100, 96, 180, 116, 110, 110, 116]

    def test_everything_fits_on_one_row_when_there_is_room(self) -> None:
        by_rank, _ = _grille(self.MEETINGS, 2000)
        assert by_rank == len(self.MEETINGS)

    def test_missing_room_wraps_to_the_next_line(self) -> None:
        by_rank, _ = _grille(self.MEETINGS, 500)
        assert by_rank < 7

    def test_the_rows_are_balanced(self) -> None:
        """Eight buttons over two rows give 4 and 4, never 6 and 2.

        A full first row against an almost empty second one is the most visible defect
        of a bar that wraps.
        """
        by_rank, _ = _grille(self.MEETINGS, 775)
        assert by_rank == 4
        assert len(self.MEETINGS) - by_rank == 4

    def test_every_column_has_the_same_width(self) -> None:
        """Edges that do not line up read as sloppy."""
        _, colonne = _grille(self.MEETINGS, 775)
        assert colonne >= max(self.MEETINGS), "au moins la largeur du plus large"

    def test_the_stretching_is_capped(self) -> None:
        """Filling without a limit gave 290 px buttons for an "Ouvrir" that needs 96,
        stretched over nothing. A button out of proportion is as badly laid out as one
        that overflows.
        """
        from greffier.interface.readable import ETIREMENT_MAXIMUM

        _, colonne = _grille(self.MEETINGS, 2000)
        assert colonne <= max(self.MEETINGS) * ETIREMENT_MAXIMUM

    def test_the_longest_label_fits_the_minimum_width(self) -> None:
        """This is what keeps "Envoyer par courriel" whole: four columns of 187 px fit
        inside the 775 px available.
        """
        by_rank, colonne = _grille(self.MEETINGS, 775)
        assert by_rank == 4
        assert colonne >= max(self.MEETINGS)

    def test_nothing_ever_sticks_out_of_the_width(self) -> None:
        for offerte in range(200, 1500, 17):
            by_rank, colonne = _grille(self.MEETINGS, offerte)
            largeur_totale = by_rank * colonne + (by_rank - 1) * 9
            assert by_rank >= 1
            if by_rank > 1:
                assert largeur_totale <= offerte, offerte

    def test_squeezed_down_one_column_is_left(self) -> None:
        """Zéro colonne ferait disparaître la barre entière."""
        by_rank, colonne = _grille(self.MEETINGS, 10)
        assert by_rank == 1
        assert colonne == max(self.MEETINGS), "le bouton garde sa largeur minimale"

    def test_with_no_button_the_computation_does_not_raise(self) -> None:
        assert _grille([], 800) == (1, 0)


class TestAFailurePublishedToTheState:
    """A failure in the chain must be written into the state, not only on screen.

    The defect, seen on 2026-09-10 on a meeting of one hour forty-two: the chain
    failed at the sending, the failure was reported only through a modal dialogue,
    and the state stayed frozen on "envoi". Screen locked, nobody to click.
    Everything that reads that state: the watch, the command line, rebuilding the
    application, believed a meeting was still being processed, two hours after it
    had ended.
    """

    def _config_in(self, tmp_path: Path):
        from greffier.adapters.configuration import Config

        return Config(paths={"donnees": tmp_path, "modeles": tmp_path / "modeles"})

    def _a_state_under_way(self, tmp_path: Path, identifier: str) -> Path:
        import json

        state = tmp_path / "etat.json"
        state.write_text(json.dumps({
            "phase": "envoi", "message": "Envoi du compte rendu…",
            "nom": "reunion", "identifiant": identifier,
            "audio": str(tmp_path / f"{identifier}.wav"),
        }), encoding="utf-8")
        return state

    def _publish(
        self, tmp_path: Path, identifier: str, trouble: Exception,
        dans_l_etat: str | None = None,
    ) -> dict:
        import json

        from greffier.interface.window import Window

        state = self._a_state_under_way(tmp_path, dans_l_etat or identifier)
        # Sans Tk : la méthode ne lit que `self.config`, et c'est justement ce
        # qui la rend éprouvable sans écran.
        without_a_screen = type("SansEcran", (), {"config": self._config_in(tmp_path)})()
        Window._publish_the_failure(without_a_screen, identifier, trouble)
        return json.loads(state.read_text(encoding="utf-8"))

    def test_the_phase_stops_lying(self, tmp_path: Path) -> None:
        state = self._publish(tmp_path, "2026-09-10_10h10_reunion", RuntimeError("boum"))
        assert state["phase"] == "echec", state

    def test_the_reason_is_kept(self, tmp_path: Path) -> None:
        """So that it can be read afterwards, once the modal window has gone."""
        state = self._publish(
            tmp_path, "2026-09-10_10h10_reunion", RuntimeError("Outlook refuse")
        )
        assert "Outlook refuse" in state["message"]

    def test_the_state_of_another_meeting_is_untouched(self, tmp_path: Path) -> None:
        """The rule of the log: it writes only when the state carries this meeting."""
        state = self._publish(
            tmp_path, "2026-09-10_11h00_autre", RuntimeError("boum"),
            dans_l_etat="2026-09-10_10h10_reunion",
        )
        assert state["phase"] == "envoi"

    def test_an_unreadable_state_reports_nothing(self, tmp_path: Path) -> None:
        """An error is already being handled: a second one here would lose the message of
        the first.
        """
        from greffier.interface.window import Window

        (tmp_path / "etat.json").write_text("{ ceci n'est pas du json", encoding="utf-8")
        without_a_screen = type("SansEcran", (), {"config": self._config_in(tmp_path)})()
        Window._publish_the_failure(without_a_screen, "peu-importe", RuntimeError("boum"))


class TestPreparingAMeetingFromTheWindow:
    """Talking to her before a meeting, and the window keeping it.

    The conversation refused, outside a meeting, to talk about anything: it
    wanted a meeting that already existed. What was gathered in front of it was
    lost, and the meeting then started from nothing.
    """

    def _fenetre(self, tmp_path, preparation=None, langue="fr"):
        """The window without a screen: these methods only read `self`.

        The language is said rather than inherited: the sentences these methods
        produce are translated, and a test that read the machine's language
        would pass here and fail on a runner set to English -- which is exactly
        what it did.
        """
        from greffier.adapters.configuration import Config

        config = Config()
        config.interface.language = langue
        config.paths.data = tmp_path
        from greffier.interface.window import Window

        sans_ecran = type("SansEcran", (), {
            "config": config,
            "_preparation": preparation,
            "dits": [],
            "demandes": [],
            # The same wording the window uses: these methods say things, and a
            # test that stubbed the sentences would check nothing about them.
            "dit": Window.dit,
        })()
        return sans_ecran

    def test_a_spoken_question_goes_to_the_preparation_when_there_is_one(
            self, tmp_path):
        from greffier.domain.preparation import Preparation
        from greffier.interface.window import Window

        fenetre = self._fenetre(tmp_path, Preparation(identifier="p", subject="recette"))
        fenetre._answer_while_preparing = lambda q: fenetre.demandes.append(q)
        Window._ask_this(fenetre, "rappelle-moi la dernière")
        assert fenetre.demandes == ["rappelle-moi la dernière"]

    def test_without_a_preparation_it_goes_where_it_always_went(self, tmp_path):
        """Preparing must not change what the tab already did."""
        from greffier.interface.window import Window

        fenetre = self._fenetre(tmp_path)
        pose = []

        class Champ:
            def delete(self, *a):
                pass

            def insert(self, _i, texte):
                pose.append(texte)

        fenetre.question = Champ()
        fenetre._ask = lambda: pose.append("posée")
        Window._ask_this(fenetre, "et le compte rendu ?")
        assert pose == ["et le compte rendu ?", "posée"]

    def test_a_button_merely_tapped_says_so_rather_than_transcribing_nothing(
            self, tmp_path):
        from greffier.interface.window import Window

        fenetre = self._fenetre(tmp_path, langue="fr")
        fenetre._dictee = type("Rien", (), {"stop": lambda self: None})()
        fenetre.bouton_parler = type("Bouton", (), {"set_caption": lambda self, t: None})()
        fenetre._say_while_preparing = lambda genre, texte: fenetre.dits.append(texte)
        Window._stop_dictating(fenetre)
        assert any("maintiens le bouton" in dit for dit in fenetre.dits)

    def test_it_says_it_in_the_language_of_the_machine(self, tmp_path):
        """The same refusal, in English, on a machine that reads English."""
        from greffier.interface.window import Window

        fenetre = self._fenetre(tmp_path, langue="en")
        fenetre._dictee = type("Rien", (), {"stop": lambda self: None})()
        fenetre.bouton_parler = type("Bouton", (), {"set_caption": lambda self, t: None})()
        fenetre._say_while_preparing = lambda genre, texte: fenetre.dits.append(texte)
        Window._stop_dictating(fenetre)
        assert any("hold the button" in dit for dit in fenetre.dits)

    def test_releasing_without_having_pressed_costs_nothing(self, tmp_path):
        from greffier.interface.window import Window

        fenetre = self._fenetre(tmp_path)
        fenetre._dictee = None
        fenetre.bouton_parler = type("Bouton", (), {"set_caption": lambda self, t: None})()
        Window._stop_dictating(fenetre)
