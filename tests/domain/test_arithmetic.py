"""How many threads the models receive, and why not all of them.

ONNX models only take one by default, and the segmentation then the
voiceprints are the longest part of the processing: seven cores out of eight
were waiting. Measured on a hundred-and-five-second interview: 287 s on one
thread, 206 s on two, 167 s on four, 193 s on eight. Taking all of them is
worse than half, and this test freezes that finding.
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
        """The watch runs during the meeting: taking everything would hinder it."""
        assert compute_threads(8) < 8

    def test_a_machine_that_will_not_say_how_many_cores(self, monkeypatch):
        """os.cpu_count() returns None in some containers: two assumed cores
        beat the exception, and one thread beats zero."""
        monkeypatch.setattr(arithmetic.os, "cpu_count", lambda: None)
        assert compute_threads() == 1

    def test_the_machine_is_asked_when_nobody_says(self, monkeypatch):
        monkeypatch.setattr(arithmetic.os, "cpu_count", lambda: 16)
        assert compute_threads() == 8

    def test_a_thread_count_is_a_whole_number(self):
        """A real division would return 4.0, which the models refuse."""
        assert isinstance(compute_threads(9), int)
        assert isinstance(compute_threads(8), int)


class TestChosenDevice:
    """What the models run on, when nothing says.

    Measured on a 40.7 s meeting, same models and same turns returned: 43 s of
    cutting into speaker turns on the processor, 5.8 s on the card. The
    default choice therefore has to be the card as soon as there is one.
    """

    def test_the_card_when_there_is_one(self):
        assert chosen_device("auto", a_card_answers=True) == "cuda"

    def test_the_processor_when_there_is_none(self):
        assert chosen_device("auto", a_card_answers=False) == "cpu"

    def test_asking_for_the_processor_is_honoured(self):
        """A card shared with something else is refused."""
        assert chosen_device("cpu", a_card_answers=True) == "cpu"

    def test_asking_for_a_card_that_is_not_there_falls_back(self):
        """Les mêmes réglages voyagent d'une machine à l'autre."""
        assert chosen_device("cuda", a_card_answers=False) == "cpu"

    def test_asking_for_the_card_that_is_there(self):
        assert chosen_device("cuda", a_card_answers=True) == "cuda"

    def test_anything_else_is_read_as_auto(self):
        """A typo must not prevent a meeting."""
        assert chosen_device("gpu", a_card_answers=True) == "cuda"
        assert chosen_device("", a_card_answers=False) == "cpu"
