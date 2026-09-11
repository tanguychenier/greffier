"""Le rapprochement des voix, sur des vecteurs écrits à la main."""

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
        """Deux extraits de la même voix, l'un fort l'autre faible, restent identiques."""
        assert math.isclose(similarity(voice(1.0, 2.0, 3.0), voice(10.0, 20.0, 30.0)), 1.0)

    def test_an_extract_with_no_speech_is_refused(self):
        with pytest.raises(ValueError, match="vecteur nul"):
            normalise([0.0, 0.0, 0.0])

    def test_comparing_different_sizes_is_an_error(self):
        with pytest.raises(ValueError, match="tailles différentes"):
            similarity(voice(1.0, 0.0), voice(1.0, 0.0, 0.0))


class TestAggregating:
    def test_long_extracts_weigh_more(self):
        """Une minute d'explication compte plus que trois secondes de « d'accord »."""
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
        """Résultat normal et fréquent : on demandera à l'utilisateur."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        assert recognise(voice(0.0, 0.0, 1.0), bank) is None

    def test_two_close_voices_make_it_hesitate(self):
        """Sans marge suffisante, mieux vaut ne rien affirmer."""
        bank = [
            Person("Josiane", [voice(1.0, 0.02, 0.0)]),
            Person("Jocelyne", [voice(1.0, 0.0, 0.02)]),
        ]
        assert recognise(voice(1.0, 0.01, 0.01), bank) is None

    def test_an_empty_bank_returns_nothing(self):
        assert recognise(voice(1.0, 0.0), []) is None
        assert recognise(voice(1.0, 0.0), [Person("Josiane", [])]) is None

    def test_the_best_extract_is_kept_not_the_average(self):
        """Enregistrée au casque puis en salle, une personne a deux signatures :
        leur moyenne ne ressemblerait à aucune des deux."""
        au_casque = voice(1.0, 0.0, 0.0)
        en_salle = voice(0.0, 1.0, 0.0)
        bank = [Person("Josiane", [au_casque, en_salle]),
                  Person("Marc", [voice(0.3, 0.3, 0.9)])]
        found = recognise(voice(0.05, 0.99, 0.0), bank)
        assert found is not None and found.name == "Josiane"

    def test_the_thresholds_can_be_adjusted(self):
        """Une salle réverbérante abaisse la similarité : le seuil doit suivre."""
        bank = [Person("Josiane", [voice(1.0, 0.0, 0.0)])]
        # 0,26 de similarité : sous le seuil mesuré de 0,45.
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
        """Épinglé pour que personne ne les abaisse sans le vouloir.

        Le seuil **a** été abaissé le 2026-09-09, de 0,70 à 0,45, et c'est une
        mesure qui l'a décidé : sur le corpus AMI, 4 personnes reconnues sur 7
        au lieu de 3, sans aucune confusion. Ce test garde la borne basse pour
        que le prochain changement soit lui aussi mesuré.
        """
        assert RECOGNITION_THRESHOLD >= 0.4
        assert MINIMUM_MARGIN > 0, "c'est la marge qui rend le seuil bas sans danger"
        assert MINIMUM_MARGIN > 0


class TestJoiningVoices:
    """La segmentation éclate une même voix : il faut la recoller."""

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
        """L'utilisateur écoutera un extrait : autant que ce soit le plus long."""
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
        """A proche de B, B proche de C, mais A loin de C : on ne réunit pas tout.

        L'agrégat est recalculé après chaque réunion, ce qui empêche une suite
        de petits pas de rassembler des voix qui n'ont rien à voir.
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
        """0,45 vient d'une mesure, pas d'une intuition.

        Le corpus AMI, quatre séries, en interrogeant la séance b contre une
        banque faite de la séance a : 0,70 reconnaissait 3 personnes sur 7,
        0,45 en reconnaît 4, et 0,30 en reconnaîtrait 5 au prix d'une
        confusion.
        """
        assert RECOGNITION_THRESHOLD == 0.45

    def test_declaring_a_conflict_demands_more(self):
        """Un conflit fait taire un nom : le déclarer à la légère revient à ne
        plus reconnaître personne. Deux personnes différentes se mesurent
        jusqu'à 0,652 sur le corpus."""
        from greffier.domain.voiceprints import CONFLICT_THRESHOLD

        assert CONFLICT_THRESHOLD > RECOGNITION_THRESHOLD
        assert CONFLICT_THRESHOLD >= 0.7
        assert JOIN_THRESHOLD > RECOGNITION_THRESHOLD

    def test_two_small_groups_do_not_join_on_an_accident(self):
        """Un agrégat tiré de peu de matière est bruité : la similarité seule
        ne suffit pas. Constaté sur un jeu d'essai à trois locuteurs
        synthétiques, où deux petits groupes ont franchi SEUIL_FUSION par
        accident statistique.
        """
        per_voice = {
            "v1": [voice(1.0, 0.01, duration=4.0)],
            "v2": [voice(0.99, 0.1, duration=4.0)],
        }
        membership = join_voices(per_voice)
        assert membership["v1"] != membership["v2"]

    def test_a_big_voice_still_absorbs_the_thin_fragments(self):
        """La garde de matière ne doit pas empêcher le recollage ordinaire :
        une voix déjà établie absorbe sans contrainte nouvelle."""
        per_voice = {
            "etablie": [voice(1.0, 0.0, duration=120.0)],
            "fragment": [voice(0.99, 0.1, duration=1.0)],
        }
        membership = join_voices(per_voice)
        assert membership["fragment"] == membership["etablie"] == "etablie"

    def test_the_guard_on_material_is_written_down(self):
        assert MINIMUM_JOIN_MATERIAL > 0


class TestABankThatContradictsItself:
    """Une banque où deux noms portent la même voix ne peut plus trancher.

    Mesuré sur une banque réelle le 2026-09-02 : deux entrées à 0,77 de
    ressemblance, quand deux personnes différentes s'y mesurent entre 0,22 et
    0,53. L'une portait la voix de l'autre, nommée par erreur trois jours plus
    tôt — et depuis, chaque réunion attribuait ce nom à la mauvaise personne,
    en l'affirmant.
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
        """Se taire vaut mieux que choisir : c'est l'utilisateur qui tranchera."""
        one_of = voice(1.0, 0.0, 0.0)
        bank = [Person(name="Cédric", voiceprints=[one_of]),
                  Person(name="Tanguy", voiceprints=[voice(0.99, 0.14, 0.0)]),
                  Person(name="Sophie", voiceprints=[voice(0.0, 0.0, 1.0)])]
        assert recognise(one_of, bank) is None

    def test_the_names_outside_the_conflict_stay_recognised(self):
        """Une entrée douteuse ne doit pas rendre toute la banque muette."""
        sophie = voice(0.0, 0.0, 1.0)
        bank = [Person(name="Cédric", voiceprints=[voice(1.0, 0.0, 0.0)]),
                  Person(name="Tanguy", voiceprints=[voice(0.99, 0.14, 0.0)]),
                  Person(name="Sophie", voiceprints=[sophie])]
        match = recognise(sophie, bank)
        assert match is not None and match.name == "Sophie"

    def test_the_bank_may_be_a_generator(self):
        """Elle est parcourue deux fois : le classement, puis les conflits."""
        sophie = voice(0.0, 0.0, 1.0)
        people = [Person(name="Sophie", voiceprints=[sophie]),
                     Person(name="Katell", voiceprints=[voice(0.0, 1.0, 0.0)])]
        match = recognise(sophie, (p for p in people))
        assert match is not None and match.name == "Sophie"


class TestStitchingAfterTheMeeting:
    """Le recollage complet : paires, adoption, consolidation.

    Le cas qui a motivé ces trois passes est une réunion réelle de 92 minutes,
    trois personnes autour d'une table : la segmentation a rendu **298 voix**,
    et le recollage par paires seul n'en retirait que 126.
    """

    def test_a_fragment_joins_the_established_group_it_resembles(self):
        """Le cas de la réunion réelle, en miniature.

        Six secondes de parole ne ressemblent à aucun autre fragment, mais elles
        ressemblent à quelqu'un qui a parlé dix minutes. Sans cette passe, le
        fragment devient un participant de plus dans le compte rendu.
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
        """L'adoption rattache, elle n'invente pas : sous le seuil, on se tait."""
        per_voice = {
            "etablie": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "autre": [voice(0.0, 1.0, 0.0, duration=400.0)],
            "etrangere": [voice(0.0, 0.0, 1.0, duration=6.0)],
        }
        assert stitch(per_voice)["etrangere"] == "etrangere"

    def test_two_distinct_established_groups_do_not_merge(self):
        """Deux personnes différentes montent à 0,652 sur le corpus AMI.

        La consolidation compare des agrégats devenus fiables : c'est justement
        là qu'une erreur coûterait le plus cher, puisqu'elle réunirait deux
        participants pour de bon.
        """
        per_voice = {
            "une": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "deux": [voice(0.62, 0.78, 0.0, duration=600.0)],
        }
        membership = stitch(per_voice)
        assert membership["une"] != membership["deux"]

    def test_someone_who_moves_seats_is_brought_together(self):
        """Deux groupes fournis, trop peu semblables pour la passe des paires.

        0,72 ne franchit pas SEUIL_FUSION (0,75) : sans la consolidation, la
        même personne reste deux participants jusque dans le compte rendu.
        """
        per_voice = {
            "avant": [voice(1.0, 0.0, 0.0, duration=600.0)],
            "apres": [voice(0.72, 0.694, 0.0, duration=600.0)],
        }
        membership = stitch(per_voice)
        assert membership["avant"] == membership["apres"]

    def test_an_adopted_fragment_helps_adopt_the_next(self):
        """L'ordre cesse d'être arbitraire : on part du fragment le plus fourni.

        Une miette proche d'une autre miette, elle-même proche d'un groupe
        établi, finit dans ce groupe — à condition que la première ait été
        traitée d'abord, ce que le tri par matière garantit.
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
        """Une réunion de deux minutes n'a pas de « groupe établi ».

        Rattacher des fragments les uns aux autres sans point d'attache solide
        est exactement ce que la passe des paires fait déjà, avec la prudence
        qui convient. L'adoption se retire alors au lieu de deviner.
        """
        per_voice = {
            "a": [voice(1.0, 0.0, 0.0, duration=5.0)],
            "b": [voice(0.93, 0.37, 0.0, duration=4.0)],
        }
        membership = stitch(per_voice)
        assert membership["a"] != membership["b"]

    def test_the_stitching_thresholds_come_from_a_measurement(self):
        """Rejoués sur la réunion réelle par `tools/replay_stitching.py`.

        298 voix rendues par la segmentation, 172 après la passe des paires,
        24 après l'adoption, 23 après la consolidation — dont 3 portent plus de
        dix secondes, soit le nombre exact de personnes présentes. Aucun groupe
        ne réunit deux personnes, contrôlé contre les noms posés à la main.
        """
        assert ADOPTION_THRESHOLD == 0.45
        assert ADOPTION_MARGIN == 0.0
        assert CONSOLIDATION_THRESHOLD == 0.70
        assert ESTABLISHED_MATERIAL == 30.0
