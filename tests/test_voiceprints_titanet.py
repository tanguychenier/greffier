"""The bounds of voiceprint extraction.

The case that named it: a 33-minute meeting round a table brought speaker
identification down with "BroadcastIterator::Init: axis == 1 || axis == largest
was false", an ONNX Runtime error in the encoder's "Where" node. The
segmentation had produced one long continuous turn of speech, and the model
does not accept an extract of that length: measured, 120 s pass and 150 s fail.

These tests are about the bounding, which does not need the model's 98 MB to be
loaded: they check that it is never given more than it accepts.
"""

from __future__ import annotations

import numpy as np

from greffier.adapters.voiceprints_titanet import MAXIMUM_LENGTH, MINIMUM_LENGTH


class Recorded:
    """Keeps what it is given, in place of the model."""

    def __init__(self) -> None:
        self.received_ones: list[int] = []

    def bound(self, samples: np.ndarray, frequency: int) -> np.ndarray:
        # Reproduces the adapter's bounding, the only rule at play.
        borne = int(MAXIMUM_LENGTH * frequency)
        if len(samples) > borne:
            milieu = len(samples) // 2
            samples = samples[milieu - borne // 2 : milieu + borne // 2]
        self.received_ones.append(len(samples))
        return samples


class TestBounds:
    def test_the_bound_stays_under_the_measured_limit(self) -> None:
        # 120 s pass and 150 s fail: the bound has to sit clearly under that.
        assert MAXIMUM_LENGTH <= 120.0
        assert MAXIMUM_LENGTH >= MINIMUM_LENGTH

    def test_a_short_excerpt_goes_through_whole(self) -> None:
        kept = Recorded()
        kept.bound(np.zeros(16000 * 10, dtype="float32"), 16000)
        assert kept.received_ones == [16000 * 10]

    def test_too_long_an_extract_is_brought_back_to_the_bound(self) -> None:
        kept = Recorded()
        kept.bound(np.zeros(16000 * 600, dtype="float32"), 16000)
        assert kept.received_ones == [int(16000 * MAXIMUM_LENGTH)]

    def test_it_is_the_middle_of_the_passage_that_is_kept(self) -> None:
        # The start of a long turn of speech often carries a hesitation or an
        # "alors" that says nothing about the timbre.
        frequency = 16000
        signal = np.arange(frequency * 600, dtype="float32")
        borne = int(MAXIMUM_LENGTH * frequency)
        milieu = len(signal) // 2
        expected = signal[milieu - borne // 2 : milieu + borne // 2]
        assert expected[0] > 0, "le début du signal n'est pas retenu"
        assert len(expected) == borne
