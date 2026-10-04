"""Matching voices, on vectors written by hand."""

import math
from typing import ClassVar

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.models import Person, Voiceprint
from greffier.domain.voiceprints import (
    ADOPTION_MARGIN,
    ADOPTION_THRESHOLD,
    AMPLE_MATERIAL,
    COMMON_LEVEL,
    CONFLICT_THRESHOLD,
    CONSOLIDATION_THRESHOLD,
    ESTABLISHED_MATERIAL,
    JOIN_THRESHOLD,
    MINIMUM_JOIN_MATERIAL,
    MINIMUM_MARGIN,
    RECOGNITION_THRESHOLD,
    SHORT_MATERIAL,
    SILENCE_FLOOR,
    THRESHOLD_ON_SHORT,
    Intruder,
    adopt_fragments,
    aggregate,
    at_a_common_level,
    conflicting_names,
    consolidate,
    doubtful_entry,
    enrich,
    intruding_voiceprints,
    join_voices,
    normalise,
    one_person,
    recognise,
    similarity,
    stitch,
    threshold_for,
)


def voice(*components: float, duration: float = 10.0):
    return normalise(components, source_duration=duration)


def at_cosines(first: float, second: float = 0.0, *, duration: float = 16.0) -> Voiceprint:
    """A voiceprint exactly `first` from voice(1, 0, 0) and `second` from voice(0, 1, 0).

    Written by hand rather than normalised: the dot product with an axis reads
    the coordinate back untouched, so a test can sit on a threshold itself and
    not an ulp beside it. The default duration is a power of two for the same
    reason: aggregate weighs by it, and 0.75 × 16 / 16 is 0.75 again.
    """
    rest = math.sqrt(1.0 - first * first - second * second)
    return Voiceprint((first, second, rest), source_duration=duration)


_SAMPLES = st.lists(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False,
                              allow_infinity=False), min_size=1, max_size=64)
_DURATIONS = st.floats(min_value=0.0, max_value=120.0, allow_nan=False, allow_infinity=False)
# The first coordinate stays away from zero so the vector can be normalised
# whatever the other two draw.
_AWAY_FROM_ZERO = st.one_of(st.floats(min_value=0.05, max_value=1.0),
                            st.floats(min_value=-1.0, max_value=-0.05))
_COORDINATE = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_VECTORS = st.tuples(_AWAY_FROM_ZERO, _COORDINATE, _COORDINATE)
_VOICEPRINTS = st.builds(normalise, _VECTORS, source_duration=_DURATIONS)
_NAMES = ("Josiane", "Marc", "Sophie", "Katell")
_AXES = {"Josiane": (1.0, 0.0, 0.0), "Marc": (0.0, 1.0, 0.0), "Sophie": (0.0, 0.0, 1.0)}
# The three people a query is measured against in the property tests: one on
# each axis, so the scores read off its coordinates.
_AXIS_BANK = [Person(name, [voice(*axis)]) for name, axis in _AXES.items()]


def some_people(min_size: int = 0) -> st.SearchStrategy[list[Person]]:
    """A bank of distinct names, each with one to three voiceprints."""
    entries = st.tuples(st.sampled_from(_NAMES), st.lists(_VOICEPRINTS, min_size=1, max_size=3))
    return st.lists(entries, min_size=min_size, max_size=3, unique_by=lambda e: e[0]).map(
        lambda rows: [Person(name, voiceprints) for name, voiceprints in rows])


def some_groups() -> st.SearchStrategy[dict[str, list[Voiceprint]]]:
    """What the segmenter hands over: one to four voices, some perhaps empty."""
    return st.dictionaries(st.sampled_from(("v1", "v2", "v3", "v4")),
                           st.lists(_VOICEPRINTS, max_size=3), min_size=1, max_size=4)


class TestNormalisingAVoiceprint:
    def test_the_norm_is_one(self):
        e = voice(3.0, 4.0)
        assert math.isclose(math.sqrt(sum(x * x for x in e.vector)), 1.0)

    def test_loudness_does_not_change_the_voiceprint(self):
        """Two extracts of one voice, one loud one quiet, stay identical."""
        assert math.isclose(similarity(voice(1.0, 2.0, 3.0), voice(10.0, 20.0, 30.0)), 1.0)

    def test_an_extract_with_no_speech_is_refused(self):
        with pytest.raises(ValueError, match=r"^vecteur nul : extrait sans parole \?$"):
            normalise([0.0, 0.0, 0.0])

    def test_comparing_different_sizes_is_an_error(self):
        with pytest.raises(ValueError, match=r"^empreintes de tailles différentes : 2 et 3$"):
            similarity(voice(1.0, 0.0), voice(1.0, 0.0, 0.0))

    def test_an_extract_whose_length_is_not_given_carries_none(self):
        """It then weighs next to nothing in an aggregate, rather than a second."""
        assert normalise([1.0, 0.0]).source_duration == 0.0

    @given(vector=_VECTORS, gain=st.floats(min_value=0.01, max_value=100.0))
    def test_whatever_the_voice_its_loudness_leaves_the_voiceprint_unchanged(self, vector, gain):
        quiet = normalise(vector)
        loud = normalise([x * gain for x in vector])
        assert math.isclose(math.sqrt(math.fsum(x * x for x in quiet.vector)), 1.0)
        assert math.isclose(similarity(quiet, loud), 1.0)


class TestAggregating:
    def test_long_extracts_weigh_more(self):
        """A minute of explanation counts for more than three seconds of "d'accord"."""
        long_one = voice(1.0, 0.0, duration=60.0)
        brief = voice(0.0, 1.0, duration=3.0)
        average = aggregate([long_one, brief])
        assert similarity(average, long_one) > similarity(average, brief)

    @given(shorter=st.floats(min_value=0.0, max_value=0.5),
           extra=st.floats(min_value=0.01, max_value=0.5))
    def test_the_longer_extract_weighs_more_even_under_a_second(self, shorter, extra):
        """Two scraps of 0.2 s and 0.5 s are not the same amount of evidence."""
        brief = voice(1.0, 0.0, duration=shorter)
        longer = voice(0.0, 1.0, duration=shorter + extra)
        average = aggregate([brief, longer])
        assert similarity(average, longer) > similarity(average, brief)

    @given(voiceprints=st.lists(_VOICEPRINTS, min_size=1, max_size=5))
    def test_the_aggregate_lasts_as_long_as_everything_it_gathered(self, voiceprints):
        """Its duration is the material the stitching then weighs groups by."""
        gathered = aggregate(voiceprints)
        assert gathered.source_duration == pytest.approx(
            sum(e.source_duration for e in voiceprints))

    def test_aggregating_nothing_is_an_error(self):
        with pytest.raises(ValueError, match=r"^aucune empreinte à agréger$"):
            aggregate([])


class TestRecognising:
    def test_it_recognises_a_known_voice(self):
        josiane = Person("Josiane", [voice(1.0, 0.0, 0.0)])
        marc = Person("Marc", [voice(0.0, 1.0, 0.0)])
        found = recognise(voice(0.95, 0.05, 0.0), [josiane, marc])
        assert found is not None and found.name == "Josiane" and found.sure

    def test_an_unknown_voice_returns_nothing(self):
        """A normal and frequent outcome: the person will be asked."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        assert recognise(voice(0.0, 0.0, 1.0), bank) is None

    def test_two_close_voices_make_it_hesitate(self):
        """Without enough margin, better to assert nothing."""
        bank = [
            Person("Josiane", [voice(1.0, 0.02, 0.0)]),
            Person("Jocelyne", [voice(1.0, 0.0, 0.02)]),
        ]
        assert recognise(voice(1.0, 0.01, 0.01), bank) is None

    def test_an_empty_bank_returns_nothing(self):
        assert recognise(voice(1.0, 0.0), []) is None
        assert recognise(voice(1.0, 0.0), [Person("Josiane", [])]) is None

    def test_the_best_extract_is_kept_not_the_average(self):
        """Recorded on a headset then in a room, one person has two signatures: their
        average would resemble neither.
        """
        with_headset = voice(1.0, 0.0, 0.0)
        in_the_room = voice(0.0, 1.0, 0.0)
        bank = [Person("Josiane", [with_headset, in_the_room]),
                  Person("Marc", [voice(0.3, 0.3, 0.9)])]
        found = recognise(voice(0.05, 0.99, 0.0), bank)
        assert found is not None and found.name == "Josiane"

    def test_the_thresholds_can_be_adjusted(self):
        """A room with echo lowers the similarity: the threshold has to follow."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        # 0.26 of similarity: under the measured threshold of 0.45.
        distant = voice(0.26, 0.966, 0.0)
        assert recognise(distant, bank) is None
        assert recognise(distant, bank, threshold=0.2) is not None

    def test_a_voice_sitting_between_two_strangers_is_left_in_doubt(self):
        """Josiane and Marc have nothing in common, so no conflict silences the
        bank: it is the margin alone that keeps quiet, 0.03 being under 0.06."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)]), Person("Marc", [voice(0.0, 1.0, 0.0)])]
        assert recognise(at_cosines(0.72, 0.69), bank) is None

    def test_the_threshold_itself_is_enough(self):
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        found = recognise(at_cosines(RECOGNITION_THRESHOLD), bank)
        assert found is not None and found.name == "Josiane"
        assert found.similarity == RECOGNITION_THRESHOLD

    def test_the_minimum_margin_itself_is_enough(self):
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)]), Person("Marc", [voice(0.0, 1.0, 0.0)])]
        found = recognise(at_cosines(0.51, 0.45), bank)
        assert found is not None and found.name == "Josiane"
        assert found.margin == MINIMUM_MARGIN

    def test_alone_in_the_bank_the_margin_is_measured_against_an_opposite_voice(self):
        """The live window prints this gap as « écart »: with nobody second, the
        stand-in is as far as a voice can be, a cosine of -1."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        found = recognise(at_cosines(0.8), bank)
        assert found is not None
        assert found.margin == pytest.approx(found.similarity + 1.0)

    @given(coordinates=st.tuples(_AWAY_FROM_ZERO.map(abs), st.floats(min_value=0.0, max_value=1.0),
                                 st.floats(min_value=0.0, max_value=1.0)))
    def test_whoever_is_named_is_the_closest_and_the_match_says_how_firmly(self, coordinates):
        """Against one person per axis, the scores are the query's own coordinates."""
        query = normalise(coordinates)
        scores = sorted(zip(query.vector, _AXES, strict=True), key=lambda x: (-x[0], x[1]))
        (best, closest), (second, _), _ = scores
        found = recognise(query, _AXIS_BANK)
        if best < RECOGNITION_THRESHOLD or best - second < MINIMUM_MARGIN:
            assert found is None
        else:
            assert found is not None and found.name == closest
            assert found.similarity == pytest.approx(best)
            assert found.margin == pytest.approx(best - second)
            assert found.sure


class TestFeedingTheBank:
    def test_it_adds_a_voiceprint_and_counts_the_meeting(self):
        josiane = Person("Josiane", [voice(1.0, 0.0)])
        enrich(josiane, voice(0.9, 0.1))
        assert len(josiane.voiceprints) == 2
        assert josiane.meetings == 1

    def test_each_meeting_counts_one_more(self):
        josiane = Person("Josiane", [voice(1.0, 0.0)], meetings=3)
        enrich(josiane, voice(0.9, 0.1))
        assert josiane.meetings == 4

    def test_below_the_cap_nothing_is_reordered(self):
        """« greffier connus --nettoyer » names a voiceprint by its rank and removes
        it by that rank: a silent reordering would point at the wrong one."""
        josiane = Person("Josiane", [voice(1.0, 0.0, duration=1.0), voice(1.0, 0.0, duration=5.0)])
        enrich(josiane, voice(1.0, 0.0, duration=3.0), maximum=3)
        assert [e.source_duration for e in josiane.voiceprints] == [1.0, 5.0, 3.0]

    @given(durations=st.lists(_DURATIONS, min_size=1, max_size=12),
           maximum=st.integers(min_value=1, max_value=8))
    def test_whatever_arrives_the_entry_holds_at_most_the_cap_and_the_longest(
            self, durations, maximum):
        josiane = Person("Josiane")
        for duration in durations:
            enrich(josiane, voice(1.0, 0.0, duration=duration), maximum=maximum)
        kept = sorted(e.source_duration for e in josiane.voiceprints)
        assert len(kept) == min(len(durations), maximum)
        assert kept == sorted(durations)[len(durations) - len(kept):]
        assert josiane.meetings == len(durations)

    def test_what_is_kept_is_bounded_and_favours_long_extracts(self):
        josiane = Person("Josiane", [voice(1.0, 0.0, duration=float(i)) for i in range(1, 4)])
        for i in range(10):
            enrich(josiane, voice(1.0, 0.0, duration=100.0 + i), maximum=3)
        assert len(josiane.voiceprints) == 3
        assert min(e.source_duration for e in josiane.voiceprints) >= 100.0

    def test_the_defaults_stay_careful(self):
        """Pinned down so that nobody lowers them without meaning to.

        The threshold **was** lowered on 2026-09-09, from 0.70 to 0.45, and a
        measurement decided it: on the AMI corpus, 4 people recognised out of 7
        instead of 3, with no confusion at all. This test keeps the lower bound so
        that the next change is measured too.
        """
        assert RECOGNITION_THRESHOLD >= 0.4
        assert MINIMUM_MARGIN > 0, "c'est la marge qui rend le seuil bas sans danger"
        assert MINIMUM_MARGIN > 0


class TestJoiningVoices:
    """The segmentation shatters one voice: it has to be stitched back."""

    def test_two_close_groups_are_joined(self):
        per_voice = {
            "v1": [voice(1.0, 0.0, 0.0, duration=60.0)],
            "v2": [voice(0.99, 0.1, 0.0, duration=20.0)],
            "v3": [voice(0.0, 0.0, 1.0, duration=40.0)],
        }
        membership = join_voices(per_voice)
        assert membership["v1"] == membership["v2"]
        assert membership["v3"] != membership["v1"]

    def test_the_best_fed_group_gives_its_name(self):
        """Someone will listen to an extract: it may as well be the longest."""
        per_voice = {
            "court": [voice(1.0, 0.0, duration=5.0)],
            "long": [voice(0.99, 0.1, duration=120.0)],
        }
        membership = join_voices(per_voice)
        assert membership["court"] == "long" and membership["long"] == "long"

    def test_distinct_voices_are_not_joined(self):
        per_voice = {
            "v1": [voice(1.0, 0.0, 0.0)],
            "v2": [voice(0.0, 1.0, 0.0)],
            "v3": [voice(0.0, 0.0, 1.0)],
        }
        membership = join_voices(per_voice)
        assert len(set(membership.values())) == 3

    def test_the_chain_of_matches_does_not_drift(self):
        """A close to B, B close to C, but A far from C: nothing is all joined.

        The aggregate is recomputed after every join, which stops a series of small
        steps from gathering voices that have nothing to do with each other.
        """
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=10.0)],
            "b": [voice(0.7, 0.7, 0.0, duration=10.0)],
            "c": [voice(0.0, 1.0, 0.0, duration=10.0)],
        }
        membership = join_voices(per_voice, threshold=0.70)
        assert membership["a"] != membership["c"]

    def test_an_empty_group_is_ignored(self):
        per_voice = {"v1": [voice(1.0, 0.0)], "vide": []}
        membership = join_voices(per_voice)
        assert membership["vide"] == "vide"

    def test_the_measured_threshold_is_written_down(self):
        """0.45 comes from a measurement, not from an intuition.

        The AMI corpus, four series, querying session b against a bank made from
        session a: 0.70 recognised 3 people out of 7, 0.45 recognises 4, and 0.30
        would recognise 5 at the cost of one confusion.
        """
        assert RECOGNITION_THRESHOLD == 0.45

    def test_declaring_a_conflict_demands_more(self):
        """A conflict silences a name: declaring one lightly amounts to recognising
        nobody at all. Two different people measure up to 0.652 on the corpus.
        """
        from greffier.domain.voiceprints import CONFLICT_THRESHOLD

        assert CONFLICT_THRESHOLD > RECOGNITION_THRESHOLD
        assert CONFLICT_THRESHOLD >= 0.7
        assert JOIN_THRESHOLD > RECOGNITION_THRESHOLD

    def test_two_small_groups_do_not_join_on_an_accident(self):
        """An aggregate drawn from little material is noisy: similarity alone is not
        enough. Seen on a test set of three synthetic speakers, where two small
        groups passed the join threshold by statistical accident.
        """
        per_voice = {
            "v1": [voice(1.0, 0.01, duration=4.0)],
            "v2": [voice(0.99, 0.1, duration=4.0)],
        }
        membership = join_voices(per_voice)
        assert membership["v1"] != membership["v2"]

    def test_a_big_voice_still_absorbs_the_thin_fragments(self):
        """The guard on material must not stop ordinary stitching: a voice already
        established absorbs with no new constraint.
        """
        per_voice = {
            "etablie": [voice(1.0, 0.0, duration=120.0)],
            "fragment": [voice(0.99, 0.1, duration=1.0)],
        }
        membership = join_voices(per_voice)
        assert membership["fragment"] == membership["etablie"] == "etablie"

    def test_the_guard_on_material_is_written_down(self):
        assert MINIMUM_JOIN_MATERIAL > 0

    def test_six_seconds_are_enough_to_take_in_a_scrap(self):
        """The floor on material is inclusive: a voice holding exactly the minimum
        may absorb a fragment that resembles it."""
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=MINIMUM_JOIN_MATERIAL)],
            "b": [at_cosines(0.9, duration=2.0)],
        }
        assert join_voices(per_voice) == {"a": "a", "b": "a"}

    def test_the_ample_threshold_itself_is_enough(self):
        """Two established voices at exactly 0.75 are one person."""
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=64.0)],
            "b": [at_cosines(JOIN_THRESHOLD, duration=64.0)],
        }
        assert join_voices(per_voice) == {"a": "a", "b": "a"}

    def test_the_threshold_handed_in_is_the_one_applied(self):
        """A replay with a lower threshold has to join what the default refuses."""
        per_voice = {
            "une": [voice(1.0, 0.0, 0.0, duration=60.0)],
            "autre": [at_cosines(0.70, duration=60.0)],
        }
        assert len(set(join_voices(per_voice).values())) == 2
        assert len(set(join_voices(per_voice, threshold=0.65).values())) == 1

    def test_on_equal_material_the_first_name_survives(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=30.0)],
            "b": [at_cosines(0.9, duration=30.0)],
        }
        assert join_voices(per_voice) == {"a": "a", "b": "a"}

    def test_between_two_equal_candidates_the_first_names_are_joined_first(self):
        """b and c sit at 0.6 from a on either side; once a has taken b in, c no
        longer reaches the pair. Which of the two is kept must not depend on the
        order the segmenter handed the voices over in."""
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=10.0)],
            "b": [Voiceprint((0.6, 0.8, 0.0), source_duration=10.0)],
            "c": [Voiceprint((0.6, -0.8, 0.0), source_duration=10.0)],
        }
        assert join_voices(per_voice) == {"a": "a", "b": "a", "c": "c"}

    @given(per_voice=some_groups())
    def test_every_voice_ends_up_in_a_group_that_stands_on_its_own(self, per_voice):
        """Whatever the stitching did, following the map once is following it
        for good, and a voice with no voiceprint is left where it was."""
        membership = stitch(per_voice)
        assert set(membership) == set(per_voice)
        for voice_id, into in membership.items():
            assert membership[into] == into
            if not per_voice[voice_id]:
                assert into == voice_id


class TestABankThatContradictsItself:
    """A bank where two names carry the same voice can no longer decide.

    Measured on a real bank on 2026-09-02: two entries at 0.77 of likeness, when
    two different people measure between 0.22 and 0.53 against each other. One
    carried the other's voice, named by mistake three days earlier, and every
    meeting since had been attributing that name to the wrong person, and
    asserting it.
    """

    def test_two_names_on_one_voice_are_flagged(self):
        one_of = voice(1.0, 0.0, 0.0)
        almost = voice(0.99, 0.14, 0.0)
        bank = [Person(name="Cédric", voiceprints=[one_of]),
                  Person(name="Tanguy", voiceprints=[almost]),
                  Person(name="Sophie", voiceprints=[voice(0.0, 0.0, 1.0)])]
        conflicts = conflicting_names(bank)
        assert conflicts == {"Cédric": {"Tanguy"}, "Tanguy": {"Cédric"}}
        assert "Sophie" not in conflicts

    def test_a_sound_bank_flags_nothing(self):
        bank = [Person(name="Sophie", voiceprints=[voice(1.0, 0.0, 0.0)]),
                  Person(name="Katell", voiceprints=[voice(0.0, 1.0, 0.0)])]
        assert conflicting_names(bank) == {}

    def test_no_name_is_asserted_when_the_bank_contradicts_itself(self):
        """Keeping quiet beats choosing: the person will decide."""
        one_of = voice(1.0, 0.0, 0.0)
        bank = [Person(name="Cédric", voiceprints=[one_of]),
                  Person(name="Tanguy", voiceprints=[voice(0.99, 0.14, 0.0)]),
                  Person(name="Sophie", voiceprints=[voice(0.0, 0.0, 1.0)])]
        assert recognise(one_of, bank) is None

    def test_the_names_outside_the_conflict_stay_recognised(self):
        """One doubtful entry must not silence the whole bank."""
        sophie = voice(0.0, 0.0, 1.0)
        bank = [Person(name="Cédric", voiceprints=[voice(1.0, 0.0, 0.0)]),
                  Person(name="Tanguy", voiceprints=[voice(0.99, 0.14, 0.0)]),
                  Person(name="Sophie", voiceprints=[sophie])]
        match = recognise(sophie, bank)
        assert match is not None and match.name == "Sophie"

    def test_the_bank_may_be_a_generator(self):
        """It is walked twice: the ranking, then the conflicts."""
        sophie = voice(0.0, 0.0, 1.0)
        people = [Person(name="Sophie", voiceprints=[sophie]),
                     Person(name="Katell", voiceprints=[voice(0.0, 1.0, 0.0)])]
        match = recognise(sophie, (p for p in people))
        assert match is not None and match.name == "Sophie"

    def test_it_is_the_whole_entry_that_is_compared_not_its_first_voiceprint(self):
        """Cédric's second voiceprint is Tanguy's voice, named by mistake: his
        entry as a whole now sits at 0.71 from Tanguy, his first voiceprint alone
        at 0."""
        bank = [Person(name="Cédric", voiceprints=[voice(0.0, 0.0, 1.0), voice(1.0, 0.0, 0.0)]),
                Person(name="Tanguy", voiceprints=[voice(1.0, 0.0, 0.0)])]
        assert conflicting_names(bank) == {"Cédric": {"Tanguy"}, "Tanguy": {"Cédric"}}

    def test_the_conflict_threshold_itself_is_enough(self):
        bank = [Person(name="Cédric", voiceprints=[voice(1.0, 0.0, 0.0)]),
                Person(name="Tanguy", voiceprints=[at_cosines(CONFLICT_THRESHOLD)])]
        assert conflicting_names(bank) == {"Cédric": {"Tanguy"}, "Tanguy": {"Cédric"}}

    @given(bank=some_people())
    def test_a_conflict_is_always_mutual_and_never_with_oneself(self, bank):
        conflicts = conflicting_names(bank)
        for name, others in conflicts.items():
            assert name not in others
            for other in others:
                assert name in conflicts[other]


class TestStitchingAfterTheMeeting:
    """The full stitching: pairs, adoption, consolidation.

    The case that called for these three passes is a real meeting of 92 minutes,
    three people round a table: the segmentation returned **298 voices**, and
    stitching by pairs alone removed only 126 of them.
    """

    def test_a_fragment_joins_the_established_group_it_resembles(self):
        """The case from the real meeting, in miniature.

        Six seconds of speech resemble no other fragment, but they do resemble
        somebody who spoke for ten minutes. Without this pass the fragment becomes one
        more participant in the minutes.
        """
        per_voice = {
            "beaucoup": [voice(1.0, 0.05, 0.0, duration=600.0)],
            "aussi": [voice(0.0, 1.0, 0.05, duration=400.0)],
            "miette": [voice(0.93, 0.37, 0.0, duration=6.0)],
        }
        membership = stitch(per_voice)
        assert membership["miette"] == "beaucoup"
        assert membership["aussi"] == "aussi"

    def test_a_fragment_that_resembles_nothing_stays_alone(self):
        """Adoption attaches, it does not invent: under the threshold it keeps quiet."""
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "autre": [voice(0.0, 1.0, 0.0, duration=400.0)],
            "etrangere": [voice(0.0, 0.0, 1.0, duration=6.0)],
        }
        assert stitch(per_voice)["etrangere"] == "etrangere"

    def test_two_distinct_established_groups_do_not_merge(self):
        """Two different people reach 0.652 on the AMI corpus.

        Consolidation compares aggregates that have become reliable, which is exactly
        where a mistake would cost the most, since it would join two participants for
        good.
        """
        per_voice = {
            "une": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "deux": [voice(0.62, 0.78, 0.0, duration=600.0)],
        }
        membership = stitch(per_voice)
        assert membership["une"] != membership["deux"]

    def test_someone_who_moves_seats_is_brought_together(self):
        """Two well fed groups of the same person, once the pairs pass is over.

        Measured on the SUMM-RE meetings (`docs/corpus.md`): the same person cut
        in two halves scores 0.932 at the lowest, two different people 0.730 at
        the highest. 0.90 is the same person; without consolidation she would
        stay two participants all the way into the minutes.
        """
        per_voice = {
            "avant": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "apres": [voice(0.90, 0.436, 0.0, duration=600.0)],
        }
        membership = stitch(per_voice)
        assert membership["avant"] == membership["apres"]

    def test_two_people_alike_at_seventy_percent_are_not_brought_together(self):
        """The two pairs of 036c, 0.717 and 0.704, each with minutes of speech: four
        people came out as two voices while consolidation sat at 0.70."""
        per_voice = {
            "une": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "autre": [voice(0.72, 0.694, 0.0, duration=600.0)],
        }
        membership = stitch(per_voice)
        assert membership["une"] != membership["autre"]

    def test_an_adopted_fragment_helps_adopt_the_next(self):
        """The order stops being arbitrary: it starts from the best fed fragment.

        A scrap close to another scrap, itself close to an established group, ends up
        in that group, provided the first was handled first, which sorting by material
        guarantees.
        """
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "moyenne": [voice(0.9, 0.436, 0.0, duration=20.0)],
            "mince": [voice(0.86, 0.51, 0.0, duration=3.0)],
        }
        membership = stitch(per_voice)
        assert membership["moyenne"] == "etablie"
        assert membership["mince"] == "etablie"

    def test_with_no_established_group_nothing_is_adopted(self):
        """A meeting of two minutes has no "established group".

        Attaching fragments to one another with no solid anchor is exactly what the
        pairs pass already does, with the care that calls for. Adoption withdraws
        rather than guessing.
        """
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=5.0)],
            "b": [voice(0.93, 0.37, 0.0, duration=4.0)],
        }
        membership = stitch(per_voice)
        assert membership["a"] != membership["b"]

    def test_the_stitching_thresholds_come_from_a_measurement(self):
        """Replayed on real meetings by `replay_stitching.py` and `measure_stitching.py`.

        298 voices returned by the segmentation, 172 after the pairs pass, 24 after
        adoption, 23 after consolidation, of which 3 carry more than ten seconds,
        which is the exact number of people in the room. No group joins two people,
        checked against the names given by hand.

        Consolidation was then measured against a word-for-word reference
        (`docs/corpus.md`, 2026-09-15): at 0.70 it fused two pairs of different
        people scoring 0.717 and 0.704; the same person cut in two halves never
        scores under 0.932, two different people never over 0.730. Hence 0.80.
        """
        assert ADOPTION_THRESHOLD == 0.45
        assert ADOPTION_MARGIN == 0.0
        assert CONSOLIDATION_THRESHOLD == 0.80
        assert ESTABLISHED_MATERIAL == 30.0

    def test_two_established_groups_at_seventy_percent_stay_two_people(self):
        """The pair of 036c: 0.717 between two people, each with ample material."""
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=40.0)],
            "b": [voice(0.717, 0.697, 0.0, duration=40.0)],
        }
        membership = consolidate(per_voice, {"a": "a", "b": "b"})
        assert membership["a"] != membership["b"]

    def test_two_established_groups_at_ninety_percent_are_one_person(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=40.0)],
            "b": [voice(0.93, 0.37, 0.0, duration=40.0)],
        }
        membership = consolidate(per_voice, {"a": "a", "b": "b"})
        assert membership["a"] == membership["b"]

    def test_thirty_seconds_each_are_enough_to_be_consolidated(self):
        """The floor on material is inclusive."""
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=ESTABLISHED_MATERIAL)],
            "b": [at_cosines(0.9, duration=ESTABLISHED_MATERIAL)],
        }
        assert consolidate(per_voice, {"a": "a", "b": "b"}) == {"a": "a", "b": "a"}

    def test_the_consolidation_threshold_itself_is_enough(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=32.0)],
            "b": [at_cosines(CONSOLIDATION_THRESHOLD, duration=32.0)],
        }
        assert consolidate(per_voice, {"a": "a", "b": "b"}) == {"a": "a", "b": "a"}

    def test_the_better_fed_group_gives_its_name_to_the_consolidation(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=32.0)],
            "b": [at_cosines(0.9, duration=64.0)],
        }
        assert consolidate(per_voice, {"a": "a", "b": "b"}) == {"a": "b", "b": "b"}

    def test_on_equal_material_the_first_name_survives_the_consolidation(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=32.0)],
            "b": [at_cosines(0.9, duration=32.0)],
        }
        assert consolidate(per_voice, {"a": "a", "b": "b"}) == {"a": "a", "b": "a"}

    def test_between_two_equal_candidates_the_first_names_are_consolidated_first(self):
        """b and c sit at 0.85 from a on either side; once a and b are one, the
        pair reaches c at 0.67 only, under the threshold."""
        rest = math.sqrt(1.0 - 0.85 * 0.85)
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=32.0)],
            "b": [Voiceprint((0.85, rest, 0.0), source_duration=32.0)],
            "c": [Voiceprint((0.85, -rest, 0.0), source_duration=32.0)],
        }
        membership = consolidate(per_voice, {"a": "a", "b": "b", "c": "c"})
        assert membership == {"a": "a", "b": "a", "c": "c"}

    def test_the_pairs_pass_is_held_to_the_threshold_handed_in(self):
        """Two voices of a minute each at 0.70: apart by default, one person when
        the replay lowers the pairs threshold to 0.65."""
        per_voice = {
            "une": [voice(1.0, 0.0, 0.0, duration=60.0)],
            "autre": [at_cosines(0.70, duration=60.0)],
        }
        assert len(set(stitch(per_voice).values())) == 2
        assert len(set(stitch(per_voice, pairs_threshold=0.65).values())) == 1

    def test_consolidation_is_held_to_the_threshold_handed_in(self):
        per_voice = {
            "une": [voice(1.0, 0.0, 0.0, duration=60.0)],
            "autre": [at_cosines(0.70, duration=60.0)],
        }
        assert len(set(stitch(per_voice, consolidation_threshold=0.65).values())) == 1

    def test_adoption_is_held_to_the_threshold_handed_in(self):
        """Twenty seconds at 0.55 from an established voice: the pairs pass asks
        0.675 of them and refuses, adoption asks 0.45 and takes them in, unless
        the caller raises it to 0.60."""
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "fragment": [at_cosines(0.55, duration=20.0)],
        }
        assert stitch(per_voice)["fragment"] == "etablie"
        assert stitch(per_voice, adoption_threshold=0.60)["fragment"] == "fragment"


class TestAdoptingTheFragments:
    """The pairs pass holds a 20-second voice to 0.675 against anyone, so a
    fragment resembling an established voice at 0.55 stays alone there.
    Adoption compares it with the established groups alone, at the recognition
    threshold, starting from the best fed fragment.
    """

    def test_a_fragment_the_pairs_pass_refused_is_adopted_by_the_voice_it_resembles(self):
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "fragment": [at_cosines(0.55, duration=20.0)],
        }
        membership = adopt_fragments(per_voice, {"etablie": "etablie", "fragment": "fragment"})
        assert membership == {"etablie": "etablie", "fragment": "etablie"}

    def test_thirty_seconds_make_an_established_group(self):
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=ESTABLISHED_MATERIAL)],
            "fragment": [at_cosines(0.55, duration=20.0)],
        }
        membership = adopt_fragments(per_voice, {"etablie": "etablie", "fragment": "fragment"})
        assert membership["fragment"] == "etablie"

    def test_the_adoption_threshold_itself_is_enough(self):
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=512.0)],
            "fragment": [at_cosines(ADOPTION_THRESHOLD, duration=16.0)],
        }
        membership = adopt_fragments(per_voice, {"etablie": "etablie", "fragment": "fragment"})
        assert membership["fragment"] == "etablie"

    def test_the_fragment_goes_to_the_group_it_resembles_not_to_the_first_one(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=512.0)],
            "b": [voice(0.0, 1.0, 0.0, duration=512.0)],
            "fragment": [at_cosines(0.0, 0.55)],
        }
        membership = adopt_fragments(per_voice, {"a": "a", "b": "b", "fragment": "fragment"})
        assert membership == {"a": "a", "b": "b", "fragment": "b"}

    def test_a_gap_exactly_at_the_minimum_margin_is_enough(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=512.0)],
            "b": [voice(0.0, 1.0, 0.0, duration=512.0)],
            "fragment": [at_cosines(0.75, 0.45)],
        }
        identity = {"a": "a", "b": "b", "fragment": "fragment"}
        assert adopt_fragments(per_voice, identity, minimum_margin=0.30)["fragment"] == "a"

    def test_a_fragment_between_two_hosts_stays_alone_when_the_margin_asks_more(self):
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=512.0)],
            "b": [voice(0.0, 1.0, 0.0, duration=512.0)],
            "fragment": [at_cosines(0.75, 0.45)],
        }
        identity = {"a": "a", "b": "b", "fragment": "fragment"}
        assert adopt_fragments(per_voice, identity, minimum_margin=0.31)["fragment"] == "fragment"

    def test_equally_close_to_two_hosts_the_fragment_goes_to_the_first_by_name(self):
        """What a margin of 0.0, the measured default, means: a tie still adopts."""
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=512.0)],
            "b": [voice(0.0, 1.0, 0.0, duration=512.0)],
            "fragment": [at_cosines(0.6, 0.6)],
        }
        membership = adopt_fragments(per_voice, {"a": "a", "b": "b", "fragment": "fragment"})
        assert membership["fragment"] == "a"

    def test_the_best_fed_fragment_is_handled_first_and_helps_the_next(self):
        """Three seconds at 0.44 from the established voice are refused against
        it alone, and accepted at 0.46 once the twenty seconds at 0.55 have
        joined it. Handled first, the scrap would have stayed alone."""
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "mince": [at_cosines(0.44, duration=3.0)],
            "moyenne": [at_cosines(0.55, duration=20.0)],
        }
        identity = {"etablie": "etablie", "mince": "mince", "moyenne": "moyenne"}
        membership = adopt_fragments(per_voice, identity)
        assert membership == {"etablie": "etablie", "mince": "etablie", "moyenne": "etablie"}

    def test_a_refused_fragment_does_not_stop_the_others(self):
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "loin": [voice(0.0, 0.0, 1.0, duration=20.0)],
            "proche": [at_cosines(0.55, duration=10.0)],
        }
        identity = {"etablie": "etablie", "loin": "loin", "proche": "proche"}
        membership = adopt_fragments(per_voice, identity)
        assert membership == {"etablie": "etablie", "loin": "loin", "proche": "etablie"}


class TestAVoiceThatHoldsSeveralPeople:
    """What goes into the bank is the mean of everything a voice gathered.

    A voice the cut got wrong therefore pours one person's voice into another's
    file, and a file, once wrong, is wrong at every meeting that follows.
    Measured on a real bank: an entry of 280 seconds answered to another
    person's name at 0.71 while reaching its own at 0.48.
    """

    def test_one_voiceprint_is_always_one_person(self):
        from greffier.domain.voiceprints import one_person

        assert one_person([normalise([1.0, 0.0, 0.0])])

    def test_nothing_is_always_one_person(self):
        from greffier.domain.voiceprints import one_person

        assert one_person([])

    def test_voiceprints_that_resemble_each_other_are_one_person(self):
        from greffier.domain.voiceprints import one_person

        closest = normalise([1.0, 0.05, 0.0])
        assert one_person([normalise([1.0, 0.0, 0.0]), closest])

    def test_voiceprints_that_do_not_are_several(self):
        from greffier.domain.voiceprints import one_person

        assert not one_person([normalise([1.0, 0.0, 0.0]),
                               normalise([0.0, 1.0, 0.0])])

    def test_one_stranger_among_several_is_enough(self):
        """It is the mean that is poured, so a single intruder spoils it."""
        from greffier.domain.voiceprints import one_person

        ensemble = [normalise([1.0, 0.0, 0.0]), normalise([1.0, 0.05, 0.0]),
                    normalise([0.0, 1.0, 0.0])]
        assert not one_person(ensemble)

    def test_it_is_the_threshold_that_joins_two_voices(self):
        """The same number, turned on a single voice."""
        from greffier.domain.voiceprints import JOIN_THRESHOLD, one_person

        assert one_person([normalise([1.0, 0.0]), normalise([1.0, 0.0])],
                          threshold=JOIN_THRESHOLD)

    def test_the_threshold_itself_is_enough(self):
        assert one_person([voice(1.0, 0.0, 0.0), at_cosines(JOIN_THRESHOLD)])

    @given(voiceprints=st.lists(_VOICEPRINTS, min_size=2, max_size=5), threshold=_COORDINATE)
    def test_the_answer_does_not_depend_on_the_order_of_the_voiceprints(self, voiceprints,
                                                                       threshold):
        assert one_person(voiceprints, threshold) == one_person(voiceprints[::-1], threshold)
        assert one_person(voiceprints, threshold) == one_person(voiceprints[1:] + voiceprints[:1],
                                                                threshold)


class TestTheSameLevelForEverybody:
    """The sound level must no longer decide who is who.

    Measured on a single excerpt compared with itself, attenuated: 0.999 at
    -3 dB, 0.982 at -12 dB, 0.948 at -18 dB, **0.874 at -24 dB**. The
    thresholds telling one person from two sit between 0.45 and 0.75: a tenth
    of resemblance lost to the level alone is enough to cut a person into two
    voices. After levelling: 1.000 everywhere.
    """

    def test_an_excerpt_comes_back_at_the_aimed_level(self):
        from greffier.domain.voiceprints import COMMON_LEVEL, at_a_common_level

        fort = [0.5, -0.5] * 100
        put = at_a_common_level(fort)
        rms = math.sqrt(sum(x * x for x in put) / len(put))
        assert abs(rms - COMMON_LEVEL) < 1e-6

    def test_a_quiet_excerpt_reaches_the_same_level(self):
        from greffier.domain.voiceprints import COMMON_LEVEL, at_a_common_level

        weak = [0.01, -0.01] * 100
        put = at_a_common_level(weak)
        rms = math.sqrt(sum(x * x for x in put) / len(put))
        assert abs(rms - COMMON_LEVEL) < 1e-6

    def test_silence_is_left_alone(self):
        """Multiplying a silence by a hundred makes a voice out of room noise."""
        from greffier.domain.voiceprints import at_a_common_level

        almost_nothing = [1e-6, -1e-6] * 50
        assert at_a_common_level(almost_nothing) == pytest.approx(almost_nothing)

    def test_an_empty_excerpt_costs_nothing(self):
        from greffier.domain.voiceprints import at_a_common_level

        assert at_a_common_level([]) == []

    def test_nothing_is_pushed_past_full_scale(self):
        """Clipping moves the timbre further than the level did. The gain still
        goes as far as full scale allows: the peak lands on 0.99, not under."""
        from greffier.domain.voiceprints import at_a_common_level

        a_peak = [0.001] * 999 + [0.9]
        put = at_a_common_level(a_peak)
        assert max(abs(x) for x in put) == pytest.approx(0.99)

    def test_an_excerpt_exactly_at_the_silence_floor_is_still_a_voice(self):
        """1e-4 of RMS is -80 dB: it is brought up like any other excerpt."""
        at_the_floor = [SILENCE_FLOOR, -SILENCE_FLOOR] * 50
        put = at_a_common_level(at_the_floor)
        rms = math.sqrt(sum(x * x for x in put) / len(put))
        assert abs(rms - COMMON_LEVEL) < 1e-6

    def test_a_flat_silence_comes_back_as_it_is(self):
        assert at_a_common_level([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]

    @given(samples=_SAMPLES)
    def test_whatever_the_excerpt_it_comes_out_at_the_common_level_or_at_full_scale(
            self, samples):
        """Silence is left alone; everything else lands on the common level, or
        on 0.99 of peak when the common level would have clipped it, and its
        shape is the original's times one factor."""
        put = at_a_common_level(samples)
        rms = math.sqrt(math.fsum(x * x for x in samples) / len(samples))
        if rms < SILENCE_FLOOR:
            assert put == samples
            return
        rms_after = math.sqrt(math.fsum(x * x for x in put) / len(put))
        peak = max(abs(x) for x in put)
        assert peak <= 0.99 + 1e-12
        assert math.isclose(rms_after, COMMON_LEVEL, rel_tol=1e-9) or math.isclose(peak, 0.99)
        loudest = max(range(len(samples)), key=lambda i: abs(samples[i]))
        factor = put[loudest] / samples[loudest]
        assert all(math.isclose(after, before * factor, abs_tol=1e-12)
                   for before, after in zip(samples, put, strict=True))

    def test_the_shape_is_kept(self):
        """Only the scale changes: two excerpts identical up to a factor
        have to return exactly the same thing."""
        from greffier.domain.voiceprints import at_a_common_level

        wave = [0.3, -0.1, 0.25, -0.4] * 50
        attenuated = [x * 0.06 for x in wave]
        assert at_a_common_level(wave) == pytest.approx(at_a_common_level(attenuated))


class TestTheThresholdFollowsTheMaterial:
    """The same threshold for two seconds and for a minute does not hold.

    Measured on four AMI meetings against their manual annotations, through
    the microphone in the middle of the table, which is the tool's real
    condition:

    | Material on each side | 0.75 | 0.45 |
    |---|---|---|
    | 2.5 s | 99.8 % of true pairs refused | 35.2 % refused, 0.1 % confused |
    | 10 s | 39.4 % refused | none refused, 0.5 % confused |
    | 25 s | 4.0 % refused | none refused, none confused |
    """

    def test_short_material_is_held_to_less(self):
        from greffier.domain.voiceprints import THRESHOLD_ON_SHORT, threshold_for

        assert threshold_for(2.0) == THRESHOLD_ON_SHORT
        assert threshold_for(5.0) == THRESHOLD_ON_SHORT

    def test_ample_material_keeps_the_full_threshold(self):
        """Joining two established voices is the mistake that cannot be taken back."""
        from greffier.domain.voiceprints import JOIN_THRESHOLD, threshold_for

        assert threshold_for(25.0) == JOIN_THRESHOLD
        assert threshold_for(600.0) == JOIN_THRESHOLD

    def test_it_climbs_between_the_two(self):
        from greffier.domain.voiceprints import threshold_for

        amounts = [threshold_for(m) for m in (5, 10, 15, 20, 25)]
        assert amounts == sorted(amounts)
        assert len(set(amounts)) == len(amounts)

    def test_the_ceiling_can_be_lowered_by_the_caller(self):
        from greffier.domain.voiceprints import threshold_for

        assert threshold_for(600.0, ceiling=0.6) == 0.6
        assert threshold_for(2.0, ceiling=0.6) == pytest.approx(0.45)

    def test_halfway_through_the_material_halfway_through_the_climb(self):
        """The climb is a straight line from 5 s to 25 s: 15 s is held to 0.60."""
        halfway = (SHORT_MATERIAL + AMPLE_MATERIAL) / 2
        assert threshold_for(halfway) == pytest.approx((THRESHOLD_ON_SHORT + JOIN_THRESHOLD) / 2)

    @given(material=st.floats(min_value=0.0, max_value=100.0),
           more=st.floats(min_value=0.0, max_value=10.0),
           ceiling=st.floats(min_value=THRESHOLD_ON_SHORT, max_value=1.0))
    def test_more_material_is_never_held_to_less_and_never_past_the_ceiling(
            self, material, more, ceiling):
        held_to = threshold_for(material, ceiling)
        assert THRESHOLD_ON_SHORT <= held_to <= ceiling + 1e-12
        assert threshold_for(material + more, ceiling) >= held_to

    def test_a_fragment_now_reaches_the_voice_it_belongs_to(self):
        """That was the defect: a fragment resembling an established voice at 0.60
        was refused, being asked 0.75 like a minute of speech. It then founded
        one more person."""
        from greffier.domain.voiceprints import join_voices

        established = normalise([1.0, 0.0, 0.0], source_duration=60.0)
        fragment = normalise([0.60, 0.80, 0.0], source_duration=4.0)
        membership = join_voices({"etablie": [established], "fragment": [fragment]})
        assert membership["fragment"] == membership["etablie"] == "etablie"

    def test_two_scraps_still_do_not_join_each_other(self):
        """Measured: two small groups crossed the threshold by statistical
        accident. The material floor stays, on the better fed side."""
        from greffier.domain.voiceprints import join_voices

        un = normalise([1.0, 0.0, 0.0], source_duration=3.0)
        almost = normalise([0.99, 0.14, 0.0], source_duration=3.0)
        membership = join_voices({"a": [un], "b": [almost]})
        assert len(set(membership.values())) == 2

    def test_two_people_with_ample_material_stay_apart(self):
        from greffier.domain.voiceprints import join_voices

        un = normalise([1.0, 0.0, 0.0], source_duration=60.0)
        other = normalise([0.5, 0.87, 0.0], source_duration=60.0)
        membership = join_voices({"a": [un], "b": [other]})
        assert len(set(membership.values())) == 2


class TestNamingAVoiceThatLooksLikeSomeoneElse:
    """When the person names a voice, the bank says whether it already knows it.

    The entry named by mistake on 2026-08-30 would have been caught here: the
    voice sat at 0.77 from another name, when two different people measure
    between 0.22 and 0.53. The sentence is what the window shows under the
    name field, so its words are asserted, not only its presence.
    """

    BANK: ClassVar[list[Person]] = [
        Person("Josiane", [voice(1.0, 0.0, 0.0)]), Person("Marc", [voice(0.0, 1.0, 0.0)])]

    def test_a_voice_that_resembles_nobody_raises_no_doubt(self):
        assert doubtful_entry(voice(0.0, 0.0, 1.0), "Sophie", self.BANK) == ""

    def test_her_own_voice_raises_no_doubt(self):
        assert doubtful_entry(at_cosines(0.9, 0.3), "Josiane", self.BANK) == ""

    def test_with_nobody_else_in_the_bank_there_is_nothing_to_compare_with(self):
        assert doubtful_entry(voice(1.0, 0.0, 0.0), "Josiane", self.BANK[:1]) == ""
        assert doubtful_entry(voice(1.0, 0.0, 0.0), "Sophie", []) == ""

    def test_a_new_name_on_a_voice_already_in_the_bank_is_questioned(self):
        assert doubtful_entry(at_cosines(0.8), "Sophie", self.BANK) == (
            "Cette voix ressemble à Josiane (0.80), déjà en banque. Si c'est bien "
            "Josiane, nomme-la ainsi : deux entrées pour la même personne finissent "
            "par se mettre en conflit, et alors ni l'une ni l'autre n'est reconnue."
        )

    def test_a_name_with_no_voiceprint_yet_counts_as_new(self):
        bank = [*self.BANK, Person("Sophie")]
        assert doubtful_entry(at_cosines(0.8), "Sophie", bank).startswith(
            "Cette voix ressemble à Josiane (0.80), déjà en banque.")

    def test_a_known_name_on_a_voice_closer_to_another_is_questioned(self):
        assert doubtful_entry(at_cosines(0.3, 0.8), "Josiane", self.BANK) == (
            "Cette voix ressemble davantage à Marc (0.80) qu'à Josiane (0.30). Si "
            "c'est une erreur, retire le nom : une empreinte fausse est reconnue à "
            "chaque réunion suivante."
        )

    def test_it_is_the_closest_other_who_is_named(self):
        bank = [*self.BANK, Person("Sophie", [voice(0.0, 0.0, 1.0)])]
        said = doubtful_entry(at_cosines(0.0, 0.6), "Josiane", bank)
        assert said.startswith("Cette voix ressemble davantage à Sophie (0.80) qu'à Josiane")

    def test_a_known_name_is_compared_even_when_its_own_voiceprint_has_nothing_in_common(self):
        """0.00 is a score, not the absence of one: the sentence says « qu'à
        Josiane (0.00) », it does not tell her to name the voice Marc."""
        said = doubtful_entry(at_cosines(0.0, 0.8), "Josiane", self.BANK)
        assert said.startswith("Cette voix ressemble davantage à Marc (0.80) qu'à Josiane (0.00).")

    def test_a_known_name_at_a_negative_cosine_is_compared_not_told_it_is_new(self):
        """The sentence follows the bank, not the sign of the score: Josiane is
        in it, so the voice is weighed against her, however far it sits."""
        said = doubtful_entry(at_cosines(-0.3, 0.8), "Josiane", self.BANK)
        assert said == (
            "Cette voix ressemble davantage à Marc (0.80) qu'à Josiane (-0.30). Si "
            "c'est une erreur, retire le nom : une empreinte fausse est reconnue à "
            "chaque réunion suivante."
        )

    def test_the_recognition_threshold_itself_is_enough_to_doubt(self):
        said = doubtful_entry(at_cosines(0.0, RECOGNITION_THRESHOLD), "Sophie", self.BANK)
        assert said.startswith("Cette voix ressemble à Marc (0.45), déjà en banque.")

    def test_a_gap_exactly_at_the_margin_is_enough_to_doubt(self):
        said = doubtful_entry(at_cosines(0.45, 0.51), "Josiane", self.BANK)
        assert said.startswith("Cette voix ressemble davantage à Marc (0.51) qu'à Josiane (0.45).")

    def test_within_the_margin_the_doubt_is_kept_quiet(self):
        assert doubtful_entry(at_cosines(0.46, 0.51), "Josiane", self.BANK) == ""

    def test_the_margin_handed_in_is_the_one_applied(self):
        between = at_cosines(0.45, 0.60)
        assert doubtful_entry(between, "Josiane", self.BANK) != ""
        assert doubtful_entry(between, "Josiane", self.BANK, margin=0.20) == ""

    @given(new_one=_VOICEPRINTS)
    def test_naming_a_voice_after_the_person_it_matches_best_raises_no_doubt(self, new_one):
        closest = max(_AXIS_BANK, key=lambda p: (similarity(new_one, p.voiceprints[0]), p.name))
        assert doubtful_entry(new_one, closest.name, _AXIS_BANK) == ""


class TestVoiceprintsThatBelongToSomeoneElse:
    """« greffier connus --nettoyer » removes from an entry the voiceprints that
    answer to another name better than to their own.

    Measured on the bank of a real team: an entry of 280 seconds answered to
    another person's name at 0.71 while reaching its own at 0.48. Each suspect
    is reported with its rank, which is what the command then removes by.
    """

    MARC = Person("Marc", [Voiceprint((0.0, 1.0, 0.0, 0.0), source_duration=30.0)])
    SOPHIE = Person("Sophie", [Voiceprint((0.0, 0.0, 1.0, 0.0), source_duration=30.0)])
    HOME = Voiceprint((1.0, 0.0, 0.0, 0.0), source_duration=60.0)
    NEARLY_HOME = Voiceprint((0.9, math.sqrt(1.0 - 0.81), 0.0, 0.0), source_duration=20.0)
    # 0.5 from home, 0.75 from Marc: a gap of 0.25.
    MARCS = Voiceprint((0.5, 0.75, 0.0, math.sqrt(1.0 - 0.25 - 0.5625)), source_duration=7.0)
    # 0.3 from home, 0.9 from Sophie: a gap of 0.6.
    SOPHIES = Voiceprint((0.3, 0.0, 0.9, math.sqrt(1.0 - 0.09 - 0.81)), source_duration=4.0)

    def test_an_entry_with_one_voiceprint_has_nothing_to_compare_it_with(self):
        josiane = Person("Josiane", [self.MARCS])
        assert intruding_voiceprints(josiane, [josiane, self.MARC]) == []

    def test_with_nobody_else_in_the_bank_nothing_is_suspect(self):
        josiane = Person("Josiane", [self.HOME, self.MARCS])
        assert intruding_voiceprints(josiane, [josiane]) == []
        assert intruding_voiceprints(josiane, [josiane, Person("Marc")]) == []

    def test_the_person_is_not_her_own_stranger(self):
        """Her entry is in the bank she is compared with, and must not count:
        against herself every voiceprint would score 1.0, above the 0.9 it
        reaches at home."""
        josiane = Person("Josiane", [self.HOME, self.NEARLY_HOME])
        assert intruding_voiceprints(josiane, [josiane, self.MARC]) == []

    def test_the_voiceprint_closer_to_another_name_is_pointed_out(self):
        josiane = Person("Josiane", [self.HOME, self.MARCS])
        found = intruding_voiceprints(josiane, [josiane, self.MARC])
        assert found == [Intruder(rank=1, at_home=0.5, elsewhere=0.75, who="Marc", duration=7.0)]
        assert found[0].gap == 0.25

    def test_two_voiceprints_are_enough_to_judge(self):
        josiane = Person("Josiane", [self.MARCS, self.HOME])
        assert [i.rank for i in intruding_voiceprints(josiane, [self.MARC])] == [0]

    def test_the_minimum_gap_itself_is_enough(self):
        josiane = Person("Josiane", [self.HOME, self.MARCS])
        assert len(intruding_voiceprints(josiane, [self.MARC], minimum_gap=0.25)) == 1

    def test_under_the_minimum_gap_nothing_is_said(self):
        josiane = Person("Josiane", [self.HOME, self.MARCS])
        assert intruding_voiceprints(josiane, [self.MARC], minimum_gap=0.26) == []

    def test_the_worst_offender_comes_first(self):
        josiane = Person("Josiane", [self.HOME, self.MARCS, self.SOPHIES])
        found = intruding_voiceprints(josiane, [josiane, self.MARC, self.SOPHIE])
        assert [(i.rank, i.who) for i in found] == [(2, "Sophie"), (1, "Marc")]
        assert found[0].gap == pytest.approx(0.6)

    @given(copies=st.integers(min_value=2, max_value=4), bank=some_people())
    def test_an_entry_whose_voiceprints_all_agree_has_no_intruder(self, copies, bank):
        """Each one reaches another of hers at 1.0: nobody can beat that."""
        josiane = Person("Josiane", [voice(0.6, 0.8, 0.0)] * copies)
        assert intruding_voiceprints(josiane, bank) == []

    @given(hers=st.lists(_VOICEPRINTS, min_size=2, max_size=4), bank=some_people(min_size=1),
           minimum_gap=st.floats(min_value=0.0, max_value=0.5))
    def test_each_suspect_is_reported_once_worst_first_with_the_scores_the_bank_shows(
            self, hers, bank, minimum_gap):
        katell = Person("Katell", hers)
        others = [p for p in bank if p.name != "Katell"]
        found = intruding_voiceprints(katell, bank, minimum_gap=minimum_gap)
        assert [i.gap for i in found] == sorted((i.gap for i in found), reverse=True)
        assert len({i.rank for i in found}) == len(found)
        for intruder in found:
            suspect = hers[intruder.rank]
            assert intruder.gap >= minimum_gap
            assert intruder.duration == suspect.source_duration
            assert intruder.at_home == max(similarity(suspect, e)
                                           for i, e in enumerate(hers) if i != intruder.rank)
            assert intruder.elsewhere == max(similarity(suspect, e) for p in others
                                             for e in p.voiceprints if p.name == intruder.who)
            assert all(intruder.elsewhere >= similarity(suspect, e)
                       for p in others for e in p.voiceprints)
