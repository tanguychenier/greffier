"""La veille du matériel, éprouvée sans horloge, sans carte son, sans ffmpeg."""

from __future__ import annotations

import pytest

from greffier.application.veiller_materiel import VeilleMateriel
from greffier.domaine.modeles import Phase
from greffier.domaine.peripheriques import Materiel, Peripherique, Veille

JABRA = Peripherique("Jabra EVOLVE 30 II", "jabra:1", entrees=1)
INTEGRE = Peripherique("Micro MacBook Pro", "BuiltInMicrophoneDevice", entrees=1)
BLACKHOLE = Peripherique("BlackHole 2ch", "BlackHole2ch_UID", entrees=2, sorties=2)

SANS = Materiel((BLACKHOLE, INTEGRE))
AVEC = Materiel((BLACKHOLE, INTEGRE, JABRA))


class ListeurFactice:
    def __init__(self, suite: list[Materiel]) -> None:
        self.suite = list(suite)
        self.lectures = 0

    def lire(self) -> Materiel:
        self.lectures += 1
        if not self.suite:
            return Materiel()
        return self.suite.pop(0) if len(self.suite) > 1 else self.suite[0]


class MachineFactice:
    def __init__(self, phase: Phase = Phase.ENREGISTREMENT, tours_avant_arret: int = 99) -> None:
        self.phase = phase
        self.reprises: list[str] = []
        self.signalements: list[str] = []
        self.lectures = 0
        self.tours_avant_arret = tours_avant_arret

    def lire(self):
        self.lectures += 1
        if self.lectures > self.tours_avant_arret:
            self.phase = Phase.FINALISATION
        return type("Etat", (), {"phase": self.phase})()

    def reprendre(self, raison: str):
        self.reprises.append(raison)

    def signaler(self, avertissement: str):
        self.signalements.append(avertissement)


def veilleuse(materiels, *, reconstruction=True, machine=None):
    dits: list[str] = []
    reconstruits: list[str] = []

    def reconstruire(micro: str) -> bool:
        reconstruits.append(micro)
        return reconstruction

    v = VeilleMateriel(
        machine=machine or MachineFactice(),
        listeur=ListeurFactice(materiels),
        veille=Veille(micro_voulu="Jabra EVOLVE 30 II"),
        reconstruire=reconstruire,
        prevenir=dits.append,
    )
    return v, dits, reconstruits


class TestPremierTour:
    def test_le_premier_tour_ne_fait_que_relever_l_etat(self) -> None:
        v, dits, reconstruits = veilleuse([AVEC])
        v.tour()
        assert reconstruits == [] and dits == []

    def test_un_materiel_illisible_ne_conclut_rien(self) -> None:
        # Décider sur une lecture vide reviendrait à croire que tout a été
        # débranché, et à reconstruire l'agrégé sans aucune raison.
        v, dits, reconstruits = veilleuse([Materiel(), Materiel()])
        v.tour()
        v.tour()
        assert reconstruits == [] and dits == []


class TestBranchementEnCoursDeReunion:
    def test_le_casque_branche_declenche_reconstruction_puis_reprise(self) -> None:
        machine = MachineFactice()
        v, dits, reconstruits = veilleuse([SANS, AVEC], machine=machine)
        v.tour()
        v.tour()
        assert reconstruits == ["Jabra EVOLVE 30 II"]
        assert len(machine.reprises) == 1
        assert "vient d'être branché" in machine.reprises[0]

    def test_l_utilisateur_est_prevenu(self) -> None:
        v, dits, _ = veilleuse([SANS, AVEC])
        v.tour()
        v.tour()
        assert len(dits) == 1 and "branché" in dits[0]

    def test_on_reconstruit_avant_de_rouvrir_la_capture(self) -> None:
        # Rouvrir sur un agrégé périmé perdrait le morceau en cours pour rien.
        ordre: list[str] = []
        machine = MachineFactice()
        machine.reprendre = lambda raison: ordre.append("reprise")  # type: ignore[method-assign]

        def reconstruire(micro: str) -> bool:
            ordre.append("reconstruction")
            return True

        v = VeilleMateriel(
            machine=machine,
            listeur=ListeurFactice([SANS, AVEC]),
            veille=Veille(micro_voulu="Jabra EVOLVE 30 II"),
            reconstruire=reconstruire,
        )
        v.tour()
        v.tour()
        assert ordre == ["reconstruction", "reprise"]


class TestQuandLaReconstructionEchoue:
    def test_la_capture_n_est_pas_coupee(self) -> None:
        machine = MachineFactice()
        v, dits, _ = veilleuse([SANS, AVEC], reconstruction=False, machine=machine)
        v.tour()
        v.tour()
        assert machine.reprises == []

    def test_l_echec_est_dit_plutot_que_tu(self) -> None:
        machine = MachineFactice()
        v, dits, _ = veilleuse([SANS, AVEC], reconstruction=False, machine=machine)
        v.tour()
        v.tour()
        assert len(machine.signalements) == 1
        assert "a échoué" in machine.signalements[0]
        assert "continue sur l'ancien" in machine.signalements[0]
        assert dits


class TestPlusAucunMicro:
    def test_l_outil_alerte_sans_rouvrir_de_morceau(self) -> None:
        machine = MachineFactice()
        v, dits, reconstruits = veilleuse(
            [AVEC, Materiel((BLACKHOLE,))], machine=machine
        )
        v.tour()
        v.tour()
        assert machine.reprises == []
        assert reconstruits == []
        assert "n'est plus enregistrée" in machine.signalements[0]


class TestBoucle:
    def test_la_veille_s_arrete_avec_l_enregistrement(self) -> None:
        machine = MachineFactice(tours_avant_arret=3)
        v, _, _ = veilleuse([AVEC], machine=machine)
        tours = v.boucler(dormir=lambda _: None)
        assert tours == 3

    def test_une_veille_sur_un_enregistrement_termine_ne_tourne_pas(self) -> None:
        machine = MachineFactice(phase=Phase.REPOS)
        v, _, _ = veilleuse([AVEC], machine=machine)
        assert v.boucler(dormir=lambda _: None) == 0

    def test_un_etat_illisible_arrete_la_veille_plutot_que_de_boucler(self) -> None:
        class Cassee(MachineFactice):
            def lire(self):
                raise OSError("état illisible")

        v, _, _ = veilleuse([AVEC], machine=Cassee())
        assert v.boucler(dormir=lambda _: None) == 0

    def test_elle_dort_entre_deux_tours(self) -> None:
        sommeils: list[float] = []
        machine = MachineFactice(tours_avant_arret=2)
        v, _, _ = veilleuse([AVEC], machine=machine)
        v.boucler(dormir=sommeils.append)
        assert sommeils == [pytest.approx(4.0), pytest.approx(4.0)]
