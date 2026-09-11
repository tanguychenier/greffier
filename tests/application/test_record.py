"""La machine à états de l'enregistrement, sans carte son."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from greffier.application.record import RecorderState, Recording, _identifier
from greffier.domain.models import Phase


class FakeRecorder:
    def __init__(self, pid=4242):
        self.pid = pid
        self.demarre = []
        self.arretes = []
        self.assembles = []

    def start_recording(self, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"RIFF----WAVEfmt ")
        self.demarre.append(destination)
        return self.pid

    def stop_recording(self, processus):
        self.arretes.append(processus)

    def wire_up(self, chunks, destination):
        self.assembles.append(list(chunks))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"RIFF----WAVEfmt " * len(chunks))
        return destination

    def levels(self, audio):
        return [-30.0]


@pytest.fixture
def audio_recorder():
    return FakeRecorder()


@pytest.fixture
def recorder(tmp_path, monkeypatch, audio_recorder):
    # Le PID factice doit paraître vivant : c'est lui qui décide si un
    # enregistrement est en cours. Celui du processus de test aussi, puisque
    # c'est lui qui porte le traitement quand la chaîne publie son avancement.
    import os

    monkeypatch.setattr(
        "greffier.application.record._alive",
        lambda pid: pid in (4242, os.getpid()),
    )
    return Recording(
        audio_recorder=audio_recorder,
        dossier_audio=tmp_path / "enregistrements",
        fichier_etat=tmp_path / "etat.json",
    )


class TestTheMeetingIdentifier:
    def test_the_date_first_so_that_it_sorts(self):
        when = datetime(2026, 8, 24, 14, 30)
        assert _identifier("Point Copernic", when) == "2026-08-24_14h30_point-copernic"

    def test_accents_and_symbols_disappear(self):
        when = datetime(2026, 8, 24, 9, 5)
        assert _identifier("Réunion #4 (été)", when) == "2026-08-24_09h05_reunion-4-ete"

    def test_an_empty_name_stays_usable(self):
        """Et deux noms différents restent deux réunions.

        Ce test attendait le suffixe « _reunion », qui était le défaut même :
        tout sujet sans lettre ASCII rendait cette valeur, donc deux réunions
        tenues dans la même minute portaient le même identifiant et l'une
        écrasait l'autre. L'intention tenait, l'assertion la trahissait.
        """
        minuit = datetime(2026, 1, 1, 0, 0)
        assert _identifier("???", minuit).startswith("2026-01-01_00h00_")
        assert _identifier("???", minuit) != _identifier("!!!", minuit)

    def test_two_non_latin_subjects_do_not_overwrite_each_other(self):
        minuit = datetime(2026, 1, 1, 0, 0)
        assert _identifier("点検会議", minuit) != _identifier("Совещание", minuit)


class TestTheRecordingCycle:
    def test_at_rest_nothing_is_under_way(self, recorder):
        assert recorder.read().phase is Phase.REST

    def test_start_then_stop(self, recorder):
        state = recorder.start_recording("point recette")
        assert state.phase is Phase.RECORDING
        assert recorder.read().phase is Phase.RECORDING
        arrete = recorder.stop_recording()
        assert arrete.phase is Phase.FINALISATION
        assert recorder.audio_recorder.arretes == [4242]

    def test_the_state_survives_another_process(self, recorder, tmp_path):
        """Deux commandes séparées d'une heure : l'état est sur le disque."""
        recorder.start_recording("copil")
        other = Recording(
            audio_recorder=FakeRecorder(),
            dossier_audio=tmp_path / "enregistrements",
            fichier_etat=tmp_path / "etat.json",
        )
        assert other.read().name == "copil"
        assert other.read().phase is Phase.RECORDING

    def test_two_recordings_at_once_are_refused(self, recorder):
        recorder.start_recording("premier")
        with pytest.raises(RuntimeError, match="déjà en cours"):
            recorder.start_recording("second")

    def test_stopping_with_nothing_recording_is_an_error(self, recorder):
        with pytest.raises(RuntimeError, match="Aucun enregistrement"):
            recorder.stop_recording()

    def test_an_empty_recording_is_flagged(self, recorder, monkeypatch):
        recorder.start_recording("muet")
        state = recorder.read()
        # L'audio capté vit dans les morceaux : c'est là qu'il faut regarder.
        for morceau in state.chunks:
            morceau.write_bytes(b"")
        with pytest.raises(RuntimeError, match="vide"):
            recorder.stop_recording()

    def test_the_first_piece_is_numbered(self, recorder):
        state = recorder.start_recording("point")
        assert len(state.chunks) == 1
        assert state.chunks[0].name.endswith("-01.wav")
        assert state.chunks[0] != state.audio


class TestHardwareThatChanges:
    """Brancher un casque en cours de réunion coupe la capture en morceaux."""

    def test_resuming_opens_the_next_piece(self, recorder):
        recorder.start_recording("point")
        state = recorder.reprendre("Jabra branché en cours de réunion")
        assert len(state.chunks) == 2
        assert state.chunks[1].name.endswith("-02.wav")

    def test_the_reason_is_kept_for_the_minutes(self, recorder):
        recorder.start_recording("point")
        recorder.reprendre("Jabra branché en cours de réunion")
        assert recorder.read().events == ["Jabra branché en cours de réunion"]

    def test_the_old_capture_is_stopped_before_the_new_one(self, recorder, audio_recorder):
        recorder.start_recording("point")
        recorder.reprendre("changement")
        # Un ffmpeg laissé vivant tiendrait le périphérique et empêcherait
        # le suivant de l'ouvrir.
        assert len(audio_recorder.arretes) == 1
        assert len(audio_recorder.demarre) == 2

    def test_several_changes_pile_up(self, recorder):
        recorder.start_recording("point")
        for rank in range(3):
            recorder.reprendre(f"changement {rank}")
        state = recorder.read()
        assert len(state.chunks) == 4
        assert state.chunks[-1].name.endswith("-04.wav")
        assert len(state.events) == 3

    def test_stopping_stitches_all_the_pieces(self, recorder, audio_recorder):
        recorder.start_recording("point")
        recorder.reprendre("changement")
        state = recorder.stop_recording()
        assert len(audio_recorder.assembles) == 1
        assert len(audio_recorder.assembles[0]) == 2
        assert [m.name for m in audio_recorder.assembles[0]] == [
            f"{state.identifier}-01.wav", f"{state.identifier}-02.wav",
        ]
        # Après recollage, l'état ne connaît plus qu'un fichier : le final.
        assert state.chunks == [state.audio]

    def test_the_pieces_are_deleted_once_stitched(self, recorder):
        recorder.start_recording("point")
        avant = recorder.reprendre("changement").chunks
        recorder.stop_recording()
        assert not any(m.exists() for m in avant)

    def test_reporting_opens_no_piece(self, recorder):
        recorder.start_recording("point")
        state = recorder.report("plus aucun micro disponible")
        assert len(state.chunks) == 1
        assert state.events == ["plus aucun micro disponible"]

    def test_resuming_outside_a_recording_is_an_error(self, recorder):
        with pytest.raises(RuntimeError, match="Aucun enregistrement"):
            recorder.reprendre("changement")


class TestWhatMustNotBreak:
    def test_a_dead_process_does_not_pass_for_a_live_one(self, recorder, monkeypatch):
        """Redémarrage pendant une réunion : l'état ment, les processus non."""
        recorder.start_recording("interrompue")
        monkeypatch.setattr("greffier.application.record._alive", lambda pid: False)
        state = recorder.read()
        assert state.phase is Phase.ECHEC
        assert "conservé" in state.message

    def test_a_damaged_state_file_does_not_block(self, recorder):
        recorder.fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        recorder.fichier_etat.write_text("{ pas du json", encoding="utf-8")
        assert recorder.read().phase is Phase.REST

    def test_the_chain_publishes_its_progress_in_the_same_file(self, recorder):
        """C'est ce que lira l'icône de la barre, sans rien calculer."""
        recorder.start_recording("copil")
        recorder.publish("transcription", "Transcription…")
        state = recorder.read()
        assert state.phase is Phase.TRANSCRIPTION
        assert state.message == "Transcription…"
        assert state.name == "copil", "publier ne doit pas perdre le reste de l'état"

    def test_the_clock_starts_at_the_beginning(self):
        state = RecorderState(start=datetime.now(UTC) - timedelta(minutes=5))
        assert 290 < state.seconds < 310


class TestInterruptingTheWork:
    def test_the_processing_is_interrupted_not_the_audio(self, recorder, monkeypatch):
        tues = []
        monkeypatch.setattr("greffier.application.record._kill_tree", tues.append)
        recorder.start_recording("copil")
        recorder.publish("transcription", "Transcription…")
        state = recorder.abandon()
        assert state.phase is Phase.INTERROMPU
        assert "conservé" in state.message
        assert tues, "le processus de traitement doit être arrêté"

    def test_interrupting_with_no_processing_is_an_error(self, recorder):
        with pytest.raises(RuntimeError, match="Aucun traitement"):
            recorder.abandon()

    def test_publishing_records_the_current_process(self, recorder):
        """C'est lui qui porte la transcription puis la rédaction."""
        import os

        recorder.start_recording("copil")
        recorder.publish("redaction", "Rédaction…")
        assert recorder.read().pid == os.getpid()


class TestPausing:
    """Une interruption en réunion ne doit pas obliger à clore la séance.

    Sans pause, il fallait arrêter, ce qui lance le traitement, puis relancer :
    deux enregistrements et deux comptes rendus pour une seule réunion.
    """

    def test_pausing_stops_the_capture_without_closing_it(self, recorder, audio_recorder):
        recorder.start_recording("point")
        state = recorder.pause()
        assert state.phase is Phase.PAUSE
        assert state.pid is None
        assert len(audio_recorder.arretes) == 1
        # Le morceau déjà capté reste, rien n'est recollé pour l'instant.
        assert len(state.chunks) == 1

    def test_resuming_opens_one_more_piece(self, recorder):
        recorder.start_recording("point")
        recorder.pause()
        state = recorder.resume()
        assert state.phase is Phase.RECORDING
        assert len(state.chunks) == 2
        assert state.chunks[1].name.endswith("-02.wav")

    def test_the_paused_time_does_not_count_in_the_length(self, recorder, monkeypatch):
        from datetime import UTC, datetime, timedelta

        recorder.start_recording("point")
        state = recorder.pause()
        # Cinq minutes plus tard, on repart.
        state.suspendu_le = datetime.now(UTC) - timedelta(minutes=5)
        recorder.write(state)
        repris = recorder.resume()
        assert repris.pause_totale >= 300
        # Le chronomètre montre le temps enregistré, pas le temps écoulé.
        assert repris.seconds < 60

    def test_stopping_from_a_pause_stitches_everything(self, recorder, audio_recorder):
        recorder.start_recording("point")
        recorder.pause()
        recorder.resume()
        recorder.pause()
        state = recorder.stop_recording()
        assert len(audio_recorder.assembles[0]) == 2
        assert state.chunks == [state.audio]

    def test_pausing_outside_a_recording_is_an_error(self, recorder):
        with pytest.raises(RuntimeError, match="Aucun enregistrement"):
            recorder.pause()

    def test_resuming_without_a_pause_is_an_error(self, recorder):
        recorder.start_recording("point")
        with pytest.raises(RuntimeError, match="pas en pause"):
            recorder.resume()

    def test_the_pause_survives_rereading_the_state(self, recorder):
        recorder.start_recording("point")
        recorder.pause()
        # L'interface relit le fichier : la pause doit y être.
        assert recorder.read().phase is Phase.PAUSE
        assert recorder.read().suspendu_le is not None


class TestOneLogPerMeeting:
    """Le fichier d'état est unique, et c'est ce qui rendait --quand-meme
    dangereux : un traitement lancé pendant qu'une réunion s'enregistrait y
    publiait « terminé », la fenêtre en concluait que la réunion était finie, et
    la capture s'arrêtait. Une réunion entière a été perdue ainsi le 2026-09-09.
    """

    def recorder(self, tmp_path, identifier: str = ""):
        from greffier.application.record import RecorderState, Recording
        from greffier.domain.models import Phase

        class SilentRecorder:
            def start_recording(self, destination):
                return 1

            def stop_recording(self, processus):
                pass

            def prepare_transcript(self, audio, destination):
                return audio

            def wire_up(self, chunks, destination):
                return destination

            def levels(self, audio):
                return []

        recorder = Recording(
            SilentRecorder(), tmp_path / "audio", tmp_path / "etat.json"
        )
        if identifier:
            # Un processus vivant, sans quoi `lire` déclare l'enregistrement
            # interrompu — règle légitime, mais qui rendrait ce test faux.
            recorder.write(RecorderState(
                phase=Phase.RECORDING, identifier=identifier,
                name=identifier, pid=os.getpid(),
                message="Enregistrement en cours.",
            ))
        return recorder

    def test_another_meeting_publishes_nothing(self, tmp_path):
        recorder = self.recorder(tmp_path, "2026-09-09_11h00_en-cours")
        recorder.pour("2026-09-09_10h05_autre").publish("termine", "fini")
        relu = recorder.read()
        assert relu.identifier == "2026-09-09_11h00_en-cours"
        assert relu.phase.value == "enregistrement", (
            "la capture ne doit pas être déclarée finie"
        )
        assert relu.message == "Enregistrement en cours.", "rien n'a été publié"

    def test_the_meeting_concerned_publishes(self, tmp_path):
        recorder = self.recorder(tmp_path, "2026-09-09_10h05_reunion")
        recorder.pour("2026-09-09_10h05_reunion").publish("transcription", "en cours")
        assert recorder.read().message == "en cours"

    def test_a_state_at_rest_accepts_any_publication(self, tmp_path):
        """Le cas ordinaire d'un traitement lancé après coup."""
        recorder = self.recorder(tmp_path)
        recorder.pour("2026-09-02_17h37_reunion").publish("transcription", "en cours")
        assert recorder.read().message == "en cours"

    def test_an_unreadable_state_does_not_make_it_fail(self, tmp_path):
        recorder = self.recorder(tmp_path)
        (tmp_path / "etat.json").write_text("pas du JSON", encoding="utf-8")
        recorder.pour("x").publish("transcription", "en cours")


class TestAStateFrozenByADeadProcess:
    """Le fichier d'état survit à tout ; le processus, non.

    Le contrôle ne valait que pour l'enregistrement. Une rédaction interrompue
    laissait donc l'état figé sur « Rédaction… » avec un processus mort, et la
    fenêtre l'affichait encore le lendemain matin — mesuré le 2026-09-09,
    annonçant une réunion en cours qui n'existait plus.
    """

    def _state_of(self, tmp_path, phase, pid):
        recorder = Recording(
            audio_recorder=FakeRecorder(),
            dossier_audio=tmp_path / "audio",
            fichier_etat=tmp_path / "etat.json",
        )
        depart = recorder.read()
        depart.phase = Phase(phase)
        depart.message = "en cours…"
        depart.pid = pid
        recorder.write(depart)
        return recorder.read()

    def test_a_write_up_whose_process_died_no_longer_holds(self, tmp_path):
        state = self._state_of(tmp_path, "redaction", 999_999)
        assert state.phase is Phase.ECHEC
        assert "Rédiger" in state.message

    def test_a_dead_recording_says_it_differently(self, tmp_path):
        """Les deux se réparent différemment : autant ne pas les confondre."""
        state = self._state_of(tmp_path, "enregistrement", 999_999)
        assert state.phase is Phase.ECHEC
        assert "audio est conservé" in state.message

    def test_a_living_process_is_left_alone(self, tmp_path):
        state = self._state_of(tmp_path, "redaction", os.getpid())
        assert state.phase is Phase.REDACTION

    def test_a_finished_phase_is_untouched(self, tmp_path):
        """« Terminé » n'attend aucun processus : il n'y a rien à vérifier."""
        state = self._state_of(tmp_path, "termine", 999_999)
        assert state.phase is Phase.TERMINE
