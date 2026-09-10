"""La veille du matériel, éprouvée sans horloge, sans carte son, sans ffmpeg."""

from __future__ import annotations

import pytest

from greffier.application.watch_hardware import VeilleMateriel
from greffier.domain.devices import Materiel, Peripherique, WatchRules
from greffier.domain.models import Phase

JABRA = Peripherique("Jabra EVOLVE 30 II", "jabra:1", entrees=1)
INTEGRE = Peripherique("Micro MacBook Pro", "BuiltInMicrophoneDevice", entrees=1)
BLACKHOLE = Peripherique("BlackHole 2ch", "BlackHole2ch_UID", entrees=2, sorties=2)

SANS = Materiel((BLACKHOLE, INTEGRE))
AVEC = Materiel((BLACKHOLE, INTEGRE, JABRA))


class ListeurFactice:
    def __init__(self, suite: list[Materiel]) -> None:
        self.suite = list(suite)
        self.lectures = 0

    def read(self) -> Materiel:
        self.lectures += 1
        if not self.suite:
            return Materiel()
        return self.suite.pop(0) if len(self.suite) > 1 else self.suite[0]


class MachineFactice:
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


def veilleuse(materiels, *, reconstruction=True, recorder=None):
    dits: list[str] = []
    reconstruits: list[str] = []

    def reconstruire(mic: str) -> bool:
        reconstruits.append(mic)
        return reconstruction

    v = VeilleMateriel(
        recorder=recorder or MachineFactice(),
        lister=ListeurFactice(materiels),
        watch_rules=WatchRules(micro_voulu="Jabra EVOLVE 30 II"),
        reconstruire=reconstruire,
        notify_user=dits.append,
    )
    return v, dits, reconstruits


class TestPremierTour:
    def test_le_premier_tour_ne_fait_que_relever_l_etat(self) -> None:
        v, dits, reconstruits = veilleuse([AVEC])
        v.turn()
        assert reconstruits == [] and dits == []

    def test_un_materiel_illisible_ne_conclut_rien(self) -> None:
        # Décider sur une lecture vide reviendrait à croire que tout a été
        # débranché, et à reconstruire l'agrégé sans aucune raison.
        v, dits, reconstruits = veilleuse([Materiel(), Materiel()])
        v.turn()
        v.turn()
        assert reconstruits == [] and dits == []


class TestBranchementEnCoursDeReunion:
    def test_le_casque_branche_declenche_reconstruction_puis_reprise(self) -> None:
        recorder = MachineFactice()
        v, dits, reconstruits = veilleuse([SANS, AVEC], recorder=recorder)
        v.turn()
        v.turn()
        assert reconstruits == ["Jabra EVOLVE 30 II"]
        assert len(recorder.reprises) == 1
        assert "vient d'être branché" in recorder.reprises[0]

    def test_l_utilisateur_est_prevenu(self) -> None:
        v, dits, _ = veilleuse([SANS, AVEC])
        v.turn()
        v.turn()
        assert len(dits) == 1 and "branché" in dits[0]

    def test_on_reconstruit_avant_de_rouvrir_la_capture(self) -> None:
        # Rouvrir sur un agrégé périmé perdrait le morceau en cours pour rien.
        ordre: list[str] = []
        recorder = MachineFactice()
        recorder.reprendre = lambda because: ordre.append("reprise")  # type: ignore[method-assign]

        def reconstruire(mic: str) -> bool:
            ordre.append("reconstruction")
            return True

        v = VeilleMateriel(
            recorder=recorder,
            lister=ListeurFactice([SANS, AVEC]),
            watch_rules=WatchRules(micro_voulu="Jabra EVOLVE 30 II"),
            reconstruire=reconstruire,
        )
        v.turn()
        v.turn()
        assert ordre == ["reconstruction", "reprise"]


class TestQuandLaReconstructionEchoue:
    def test_la_capture_n_est_pas_coupee(self) -> None:
        recorder = MachineFactice()
        v, dits, _ = veilleuse([SANS, AVEC], reconstruction=False, recorder=recorder)
        v.turn()
        v.turn()
        assert recorder.reprises == []

    def test_l_echec_est_dit_plutot_que_tu(self) -> None:
        recorder = MachineFactice()
        v, dits, _ = veilleuse([SANS, AVEC], reconstruction=False, recorder=recorder)
        v.turn()
        v.turn()
        assert len(recorder.signalements) == 1
        assert "a échoué" in recorder.signalements[0]
        assert "continue sur l'ancien" in recorder.signalements[0]
        assert dits


class TestPlusAucunMicro:
    def test_l_outil_alerte_sans_rouvrir_de_morceau(self) -> None:
        recorder = MachineFactice()
        v, dits, reconstruits = veilleuse(
            [AVEC, Materiel((BLACKHOLE,))], recorder=recorder
        )
        v.turn()
        v.turn()
        assert recorder.reprises == []
        assert reconstruits == []
        assert "n'est plus enregistrée" in recorder.signalements[0]


class TestLaCaptureQuiSArrete:
    """La veille doit dire tout de suite que plus rien ne s'écrit.

    Le 2026-09-09, une réunion n'a rien enregistré et rien ne l'a signalé : le
    contrôle de silence n'existe qu'au traitement, donc après la réunion, quand
    il n'y a plus rien à rattraper.
    """

    def test_une_taille_qui_stagne_est_signalee(self):
        from greffier.domain.capture import TOURS_AVANT_ALERTE

        recorder = MachineFactice()
        v, dits, _ = veilleuse([SANS], recorder=recorder)
        v.captured_size = lambda: 4096
        for _ in range(TOURS_AVANT_ALERTE + 1):
            v.turn()
        assert any("n'avance plus" in s for s in recorder.signalements)
        assert dits, "l'utilisateur doit être prévenu, pas seulement l'état"

    def test_une_capture_qui_avance_ne_signale_rien(self):
        recorder = MachineFactice()
        v, dits, _ = veilleuse([SANS], recorder=recorder)
        bytes_read = iter(range(1000, 100000, 1000))
        v.captured_size = lambda: next(bytes_read)
        for _ in range(8):
            v.turn()
        assert recorder.signalements == []
        assert dits == []

    def test_sans_moyen_de_mesurer_la_veille_garde_son_ancien_office(self):
        """Une taille illisible ne doit pas faire crier au loup."""
        recorder = MachineFactice()
        v, dits, _ = veilleuse([SANS], recorder=recorder)
        v.captured_size = lambda: None
        for _ in range(8):
            v.turn()
        assert recorder.signalements == []


class TestLeSonTropFaible:
    """Le fichier grossit, mais il ne porte presque rien."""

    def test_un_niveau_durablement_faible_est_signale(self):
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        recorder = MachineFactice()
        v, dits, _ = veilleuse([SANS], recorder=recorder)
        v.captured_level = lambda: -55.0
        for _ in range(RELEVES_AVANT_ALERTE + 1):
            v.turn()
        assert any("trop faible" in s for s in recorder.signalements)
        assert dits

    def test_un_bon_niveau_ne_signale_rien(self):
        from greffier.domain.level import RELEVES_AVANT_ALERTE

        recorder = MachineFactice()
        v, _, _ = veilleuse([SANS], recorder=recorder)
        v.captured_level = lambda: -20.0
        for _ in range(RELEVES_AVANT_ALERTE + 2):
            v.turn()
        assert recorder.signalements == []

    def test_sans_moyen_de_mesurer_rien_n_est_dit(self):
        recorder = MachineFactice()
        v, _, _ = veilleuse([SANS], recorder=recorder)
        v.captured_level = lambda: None
        for _ in range(12):
            v.turn()
        assert recorder.signalements == []


class TestBoucle:
    def test_la_veille_s_arrete_avec_l_enregistrement(self) -> None:
        recorder = MachineFactice(tours_avant_arret=3)
        v, _, _ = veilleuse([AVEC], recorder=recorder)
        turns = v.loop(dormir=lambda _: None)
        assert turns == 3

    def test_une_veille_sur_un_enregistrement_termine_ne_tourne_pas(self) -> None:
        recorder = MachineFactice(phase=Phase.REST)
        v, _, _ = veilleuse([AVEC], recorder=recorder)
        assert v.loop(dormir=lambda _: None) == 0

    def test_un_etat_illisible_arrete_la_veille_plutot_que_de_boucler(self) -> None:
        class Cassee(MachineFactice):
            def read(self):
                raise OSError("état illisible")

        v, _, _ = veilleuse([AVEC], recorder=Cassee())
        assert v.loop(dormir=lambda _: None) == 0

    def test_elle_dort_entre_deux_tours(self) -> None:
        sommeils: list[float] = []
        recorder = MachineFactice(tours_avant_arret=2)
        v, _, _ = veilleuse([AVEC], recorder=recorder)
        v.loop(dormir=sommeils.append)
        assert sommeils == [pytest.approx(4.0), pytest.approx(4.0)]
