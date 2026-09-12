"""Combien de fils les modèles reçoivent, et pourquoi pas tous.

Les modèles ONNX n'en prennent qu'un par défaut, et la segmentation puis les
empreintes sont la partie la plus longue du traitement : sept cœurs sur huit
attendaient. Mesuré sur un entretien de cent cinq secondes : 287 s sur un fil,
206 s sur deux, 167 s sur quatre, 193 s sur huit. Tout prendre est moins bon
que la moitié, et ce test fige ce constat.
"""

from greffier.domain import arithmetic
from greffier.domain.arithmetic import chosen_device, compute_threads


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

    def test_a_machine_that_will_not_say_how_many_cores(self, monkeypatch):
        """os.cpu_count() rend None dans certains conteneurs : deux cœurs
        supposés valent mieux que l'exception, et un fil vaut mieux que zéro."""
        monkeypatch.setattr(arithmetic.os, "cpu_count", lambda: None)
        assert compute_threads() == 1

    def test_the_machine_is_asked_when_nobody_says(self, monkeypatch):
        monkeypatch.setattr(arithmetic.os, "cpu_count", lambda: 16)
        assert compute_threads() == 8

    def test_a_thread_count_is_a_whole_number(self):
        """Une division réelle rendrait 4.0, que les modèles refusent."""
        assert isinstance(compute_threads(9), int)
        assert isinstance(compute_threads(8), int)


class TestChosenDevice:
    """Sur quoi les modèles tournent, quand on ne le dit pas.

    Mesuré sur une réunion de 40,7 s, mêmes modèles et mêmes tours rendus :
    43 s de découpage en tours de parole sur le processeur, 5,8 s sur la carte.
    Le choix par défaut doit donc être la carte dès qu'il y en a une.
    """

    def test_the_card_when_there_is_one(self):
        assert chosen_device("auto", a_card_answers=True) == "cuda"

    def test_the_processor_when_there_is_none(self):
        assert chosen_device("auto", a_card_answers=False) == "cpu"

    def test_asking_for_the_processor_is_honoured(self):
        """Une carte partagée avec autre chose se refuse."""
        assert chosen_device("cpu", a_card_answers=True) == "cpu"

    def test_asking_for_a_card_that_is_not_there_falls_back(self):
        """Les mêmes réglages voyagent d'une machine à l'autre."""
        assert chosen_device("cuda", a_card_answers=False) == "cpu"

    def test_asking_for_the_card_that_is_there(self):
        assert chosen_device("cuda", a_card_answers=True) == "cuda"

    def test_anything_else_is_read_as_auto(self):
        """Une faute de frappe ne doit pas empêcher une réunion."""
        assert chosen_device("gpu", a_card_answers=True) == "cuda"
        assert chosen_device("", a_card_answers=False) == "cpu"
