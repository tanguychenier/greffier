"""La veille du matériel, éprouvée sans horloge, sans carte son, sans ffmpeg."""

from __future__ import annotations

import pytest

from greffier.application.watch_hardware import HardwareWatch
from greffier.domain.devices import Device, Hardware, WatchRules
from greffier.domain.models import Phase

JABRA = Device("Jabra EVOLVE 30 II", "jabra:1", entrees=1)
INTEGRE = Device("Micro MacBook Pro", "BuiltInMicrophoneDevice", entrees=1)
BLACKHOLE = Device("BlackHole 2ch", "BlackHole2ch_UID", entrees=2, sorties=2)

SANS = Hardware((BLACKHOLE, INTEGRE))
AVEC = Hardware((BLACKHOLE, INTEGRE, JABRA))


class FakeLister:
    def __init__(self, suite: list[Hardware]) -> None:
        self.suite = list(suite)
        self.lectures = 0

    def read(self) -> Hardware:
        self.lectures += 1
        if not self.suite:
            return Hardware()
        return self.suite.pop(0) if len(self.suite) > 1 else self.suite[0]


class FakeRecordingState:
    def __init__(self, phase: Phase = Phase.RECORDING, tours_avant_arret: int = 99) -> None:
        self.phase = phase
        self.reprises: list[str] = []
        self.signalements: list[str] = []
        self.lectures = 0
        self.tours_avant_arret = tours_avant_arret

    def read(self):
        self.lectures += 1
        if self.lectures > self.tours_avant_arret:
            self.phase = Phase.FINALISATION
        return type("Etat", (), {"phase": self.phase})()

    def reprendre(self, because: str):
        self.reprises.append(because)

    def report(self, warning: str):
        self.signalements.append(warning)


def hardware_watch(materiels, *, reconstruction=True, recorder=None):
    dits: list[str] = []
    reconstruits: list[str] = []

    def reconstruire(mic: str) -> bool:
        reconstruits.append(mic)
        return reconstruction

    v = HardwareWatch(
        recorder=recorder or FakeRecordingState(),
        lister=FakeLister(materiels),
        watch_rules=WatchRules(wanted_mic="Jabra EVOLVE 30 II"),
        reconstruire=reconstruire,
        notify_user=dits.append,
    )
    return v, dits, reconstruits


class TestTheFirstTurn:
    def test_the_first_turn_only_reads_the_state(self) -> None:
        v, dits, reconstruits = hardware_watch([AVEC])
        v.turn()
        assert reconstruits == [] and dits == []

    def test_unreadable_hardware_concludes_nothing(self) -> None:
        # Décider sur une lecture vide reviendrait à croire que tout a été
        # débranché, et à reconstruire l'agrégé sans aucune raison.
        v, dits, reconstruits = hardware_watch([Hardware(), Hardware()])
        v.turn()
        v.turn()
        assert reconstruits == [] and dits == []


class TestPluggingInMidMeeting:
    def test_a_headset_plugged_in_rebuilds_then_resumes(self) -> None:
        recorder = FakeRecordingState()
        v, dits, reconstruits = hardware_watch([SANS, AVEC], recorder=recorder)
        v.turn()
        v.turn()
        assert reconstruits == ["Jabra EVOLVE 30 II"]
        assert len(recorder.reprises) == 1
        assert "vient d'être branché" in recorder.reprises[0]

    def test_the_person_is_told(self) -> None:
        v, dits, _ = hardware_watch([SANS, AVEC])
        v.turn()
        v.turn()
        assert len(dits) == 1 and "branché" in dits[0]

    def test_it_rebuilds_before_reopening_the_capture(self) -> None:
        # Rouvrir sur un agrégé périmé perdrait le morceau en cours pour rien.
        ordre: list[str] = []
        recorder = FakeRecordingState()
        recorder.reprendre = lambda because: ordre.append("reprise")  # type: ignore[method-assign]

        def reconstruire(mic: str) -> bool:
            ordre.append("reconstruction")
            return True

        v = HardwareWatch(
            recorder=recorder,
            lister=FakeLister([SANS, AVEC]),
            watch_rules=WatchRules(wanted_mic="Jabra EVOLVE 30 II"),
            reconstruire=reconstruire,
        )
        v.turn()
        v.turn()
        assert ordre == ["reconstruction", "reprise"]


class TestWhenTheRebuildFails:
    def test_the_capture_is_not_cut(self) -> None:
        recorder = FakeRecordingState()
        v, dits, _ = hardware_watch([SANS, AVEC], reconstruction=False, recorder=recorder)
        v.turn()
        v.turn()
        assert recorder.reprises == []

    def test_the_failure_is_said_rather_than_hidden(self) -> None:
        recorder = FakeRecordingState()
        v, dits, _ = hardware_watch([SANS, AVEC], reconstruction=False, recorder=recorder)
        v.turn()
        v.turn()
        assert len(recorder.signalements) == 1
        assert "a échoué" in recorder.signalements[0]
        assert "continue sur l'ancien" in recorder.signalements[0]
        assert dits


class TestNoMicLeftAtAll:
    def test_the_tool_warns_without_opening_a_piece(self) -> None:
        recorder = FakeRecordingState()
        v, dits, reconstruits = hardware_watch(
            [AVEC, Hardware((BLACKHOLE,))], recorder=recorder
        )
        v.turn()
        v.turn()
        assert recorder.reprises == []
        assert reconstruits == []
        assert "n'est plus enregistrée" in recorder.signalements[0]


class TestACaptureThatStops:
    """La veille doit dire tout de suite que plus rien ne s'écrit.

    Le 2026-09-09, une réunion n'a rien enregistré et rien ne l'a signalé : le
    contrôle de silence n'existe qu'au traitement, donc après la réunion, quand
    il n'y a plus rien à rattraper.
    """

    def test_a_size_that_stops_growing_is_flagged(self):
        from greffier.domain.capture import TURNS_BEFORE_ALERT

        recorder = FakeRecordingState()
        v, dits, _ = hardware_watch([SANS], recorder=recorder)
        v.captured_size = lambda: 4096
        for _ in range(TURNS_BEFORE_ALERT + 1):
            v.turn()
        assert any("n'avance plus" in s for s in recorder.signalements)
        assert dits, "l'utilisateur doit être prévenu, pas seulement l'état"

    def test_a_capture_that_advances_flags_nothing(self):
        recorder = FakeRecordingState()
        v, dits, _ = hardware_watch([SANS], recorder=recorder)
        bytes_read = iter(range(1000, 100000, 1000))
        v.captured_size = lambda: next(bytes_read)
        for _ in range(8):
            v.turn()
        assert recorder.signalements == []
        assert dits == []

    def test_with_no_way_to_measure_the_watch_keeps_its_old_job(self):
        """Une taille illisible ne doit pas faire crier au loup."""
        recorder = FakeRecordingState()
        v, dits, _ = hardware_watch([SANS], recorder=recorder)
        v.captured_size = lambda: None
        for _ in range(8):
            v.turn()
        assert recorder.signalements == []


class TestSoundTooQuiet:
    """Le fichier grossit, mais il ne porte presque rien."""

    def test_a_lastingly_weak_level_is_flagged(self):
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        recorder = FakeRecordingState()
        v, dits, _ = hardware_watch([SANS], recorder=recorder)
        v.captured_level = lambda: -55.0
        for _ in range(RELEVES_AVANT_ALERTE + 1):
            v.turn()
        assert any("trop faible" in s for s in recorder.signalements)
        assert dits

    def test_a_good_level_flags_nothing(self):
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        recorder = FakeRecordingState()
        v, _, _ = hardware_watch([SANS], recorder=recorder)
        v.captured_level = lambda: -20.0
        for _ in range(RELEVES_AVANT_ALERTE + 2):
            v.turn()
        assert recorder.signalements == []

    def test_with_no_way_to_measure_nothing_is_said(self):
        recorder = FakeRecordingState()
        v, _, _ = hardware_watch([SANS], recorder=recorder)
        v.captured_level = lambda: None
        for _ in range(12):
            v.turn()
        assert recorder.signalements == []


class TestTheWholeLoop:
    def test_the_watch_stops_with_the_recording(self) -> None:
        recorder = FakeRecordingState(tours_avant_arret=3)
        v, _, _ = hardware_watch([AVEC], recorder=recorder)
        turns = v.loop(dormir=lambda _: None)
        assert turns == 3

    def test_a_watch_on_a_finished_recording_does_not_run(self) -> None:
        recorder = FakeRecordingState(phase=Phase.REST)
        v, _, _ = hardware_watch([AVEC], recorder=recorder)
        assert v.loop(dormir=lambda _: None) == 0

    def test_an_unreadable_state_stops_the_watch_rather_than_looping(self) -> None:
        class BrokenOne(FakeRecordingState):
            def read(self):
                raise OSError("état illisible")

        v, _, _ = hardware_watch([AVEC], recorder=BrokenOne())
        assert v.loop(dormir=lambda _: None) == 0

    def test_it_sleeps_between_two_turns(self) -> None:
        sommeils: list[float] = []
        recorder = FakeRecordingState(tours_avant_arret=2)
        v, _, _ = hardware_watch([AVEC], recorder=recorder)
        v.loop(dormir=sommeils.append)
        assert sommeils == [pytest.approx(4.0), pytest.approx(4.0)]
