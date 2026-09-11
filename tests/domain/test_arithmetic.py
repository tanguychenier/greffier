"""Combien de fils les modèles reçoivent, et pourquoi pas tous.

Les modèles ONNX n'en prennent qu'un par défaut, et la segmentation puis les
empreintes sont la partie la plus longue du traitement : sept cœurs sur huit
attendaient. Mesuré sur un entretien de cent cinq secondes : 287 s sur un fil,
206 s sur deux, 167 s sur quatre, 193 s sur huit. Tout prendre est moins bon
que la moitié, et ce test fige ce constat.
"""

from greffier.domain.arithmetic import compute_threads


class TestComputeThreads:
    def test_half_the_cores(self):
        assert compute_threads(8) == 4

    def test_never_fewer_than_one_thread(self):
        """Un cœur unique donnerait zéro fil, et le modèle refuserait."""
        assert compute_threads(1) == 1
        assert compute_threads(0) == 1

    def test_a_big_machine_takes_more(self):
        assert compute_threads(16) == 8

    def test_half_leaves_room_to_work(self):
        """La veille tourne pendant la réunion : tout prendre la gênerait."""
        assert compute_threads(8) < 8
