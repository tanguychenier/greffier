"""Matching voices, on vectors written by hand."""

import math

import pytest

from greffier.domain.models import Person
from greffier.domain.voiceprints import (
    ADOPTION_MARGIN,
    ADOPTION_THRESHOLD,
    CONSOLIDATION_THRESHOLD,
    ESTABLISHED_MATERIAL,
    JOIN_THRESHOLD,
    MINIMUM_JOIN_MATERIAL,
    MINIMUM_MARGIN,
    RECOGNITION_THRESHOLD,
    aggregate,
    conflicting_names,
    enrichir,
    join_voices,
    normalise,
    recognise,
    similarity,
    stitch,
)


def voice(*composantes: float, duration: float = 10.0):
    return normalise(composantes, source_duration=duration)


class TestNormalisingAVoiceprint:
    def test_the_norm_is_one(self):
        e = voice(3.0, 4.0)
        assert math.isclose(math.sqrt(sum(x * x for x in e.vector)), 1.0)

    def test_loudness_does_not_change_the_voiceprint(self):
        """Two extracts of one voice, one loud one quiet, stay identical."""
        assert math.isclose(similarity(voice(1.0, 2.0, 3.0), voice(10.0, 20.0, 30.0)), 1.0)

    def test_an_extract_with_no_speech_is_refused(self):
        with pytest.raises(ValueError, match="vecteur nul"):
            normalise([0.0, 0.0, 0.0])

    def test_comparing_different_sizes_is_an_error(self):
        with pytest.raises(ValueError, match="tailles différentes"):
            similarity(voice(1.0, 0.0), voice(1.0, 0.0, 0.0))


class TestAggregating:
    def test_long_extracts_weigh_more(self):
        """A minute of explanation counts for more than three seconds of "d'accord"."""
        longue = voice(1.0, 0.0, duration=60.0)
        breve = voice(0.0, 1.0, duration=3.0)
        moyenne = aggregate([longue, breve])
        assert similarity(moyenne, longue) > similarity(moyenne, breve)

    def test_aggregating_nothing_is_an_error(self):
        with pytest.raises(ValueError, match="aucune empreinte"):
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
        au_casque = voice(1.0, 0.0, 0.0)
        en_salle = voice(0.0, 1.0, 0.0)
        bank = [Person("Josiane", [au_casque, en_salle]),
                  Person("Marc", [voice(0.3, 0.3, 0.9)])]
        found = recognise(voice(0.05, 0.99, 0.0), bank)
        assert found is not None and found.name == "Josiane"

    def test_the_thresholds_can_be_adjusted(self):
        """A room with echo lowers the similarity: the threshold has to follow."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        # 0.26 of similarity: under the measured threshold of 0.45.
        lointaine = voice(0.26, 0.966, 0.0)
        assert recognise(lointaine, bank) is None
        assert recognise(lointaine, bank, threshold=0.2) is not None


class TestFeedingTheBank:
    def test_it_adds_a_voiceprint_and_counts_the_meeting(self):
        josiane = Person("Josiane", [voice(1.0, 0.0)])
        enrichir(josiane, voice(0.9, 0.1))
        assert len(josiane.voiceprints) == 2
        assert josiane.meetings == 1

    def test_what_is_kept_is_bounded_and_favours_long_extracts(self):
        josiane = Person("Josiane", [voice(1.0, 0.0, duration=float(i)) for i in range(1, 4)])
        for i in range(10):
            enrichir(josiane, voice(1.0, 0.0, duration=100.0 + i), maximum=3)
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
        presque = voice(0.99, 0.14, 0.0)
        bank = [Person(name="Cédric", voiceprints=[one_of]),
                  Person(name="Tanguy", voiceprints=[presque]),
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
        """Two well fed groups, too unlike each other for the pairs pass.

        0.72 does not pass the join threshold of 0.75: without consolidation the same
        person stays two participants all the way into the minutes.
        """
        per_voice = {
            "avant": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "apres": [voice(0.72, 0.694, 0.0, duration=600.0)],
        }
        membership = stitch(per_voice)
        assert membership["avant"] == membership["apres"]

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
        """Replayed on the real meeting by `tools/replay_stitching.py`.

        298 voices returned by the segmentation, 172 after the pairs pass, 24 after
        adoption, 23 after consolidation, of which 3 carry more than ten seconds,
        which is the exact number of people in the room. No group joins two people,
        checked against the names given by hand.
        """
        assert ADOPTION_THRESHOLD == 0.45
        assert ADOPTION_MARGIN == 0.0
        assert CONSOLIDATION_THRESHOLD == 0.70
        assert ESTABLISHED_MATERIAL == 30.0


class TestAVoiceThatHoldsSeveralPeople:
    """What goes into the bank is the mean of everything a voice gathered.

    A voice the cut got wrong therefore pours one person's voice into another's
    file — and a file, once wrong, is wrong at every meeting that follows.
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

        proche = normalise([1.0, 0.05, 0.0])
        assert one_person([normalise([1.0, 0.0, 0.0]), proche])

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
