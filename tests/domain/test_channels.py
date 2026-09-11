"""Qui parle, d'après le canal.

Le cas nommé : sur une réunion réelle du 25 août 2026, la voix de la personne
qui enregistrait est arrivée 12 dB sous celle des autres. Moyennée avec elles,
elle se retrouvait 18 dB sous le mélange et la segmentation ne l'a jamais vue.
Treize minutes de parole absentes du compte rendu.
"""

from __future__ import annotations

from greffier.domain.channels import ChannelSettings, local_turns, remove, subtract
from greffier.domain.models import Span

PAS = 0.025  # 25 ms, comme l'adaptateur


def levels(motif: list[tuple[float, float, int]]) -> tuple[list[float], list[float]]:
    """Construit deux suites de niveaux depuis (micro_db, systeme_db, trames)."""
    mic: list[float] = []
    system: list[float] = []
    for m, s, how_many in motif:
        mic += [m] * how_many
        system += [s] * how_many
    return mic, system


class TestAQuietVoiceThatIsStillYours:
    def test_a_voice_12_dB_under_the_others_is_still_seen(self) -> None:
        # Le cas du 25 août : le micro à -34 dB pendant que la boucle système
        # est à -22. Le moyennage la perdait ; le canal la retrouve.
        mic, system = levels([(-60, -22, 40), (-34, -50, 80), (-60, -22, 40)])
        turns = local_turns(mic, system, PAS)
        assert len(turns) == 1
        assert turns[0].duration == 80 * PAS

    def test_a_mic_quieter_than_the_loopback_is_not_kept(self) -> None:
        # Pendant que les autres parlent, le micro capte leur écho ou du bruit.
        mic, system = levels([(-34, -22, 200)])
        assert local_turns(mic, system, PAS) == []

    def test_the_margin_guards_against_the_speakers_coming_back(self) -> None:
        # Écoute par haut-parleurs : le micro réentend les enceintes, un peu
        # au-dessus de la boucle. Sans marge, tout passerait pour local.
        mic, system = levels([(-30, -33, 200)])
        assert local_turns(mic, system, PAS) == []
        # Avec une marge nulle, la même entrée est retenue : c'est bien la marge
        # qui décide, pas un autre effet.
        souple = ChannelSettings(margin_db=0.0)
        assert local_turns(mic, system, PAS, souple) != []


class TestBackgroundNoise:
    def test_the_silence_of_a_meeting_is_not_speech(self) -> None:
        # Personne ne parle : la boucle est muette, et le bruit de la pièce
        # domine. Sans plancher, tous les silences deviendraient des tours.
        mic, system = levels([(-52, -75, 400)])
        assert local_turns(mic, system, PAS) == []

    def test_the_floor_is_a_setting(self) -> None:
        mic, system = levels([(-52, -75, 400)])
        bas = ChannelSettings(floor_db=-60.0)
        assert local_turns(mic, system, PAS, bas) != []


class TestCuttingIntoTurns:
    def test_the_pauses_inside_a_sentence_do_not_cut_the_turn(self) -> None:
        # 0,5 s de silence au milieu d'une phrase : un seul tour, pas deux.
        mic, system = levels([
            (-30, -60, 40), (-60, -60, 20), (-30, -60, 40),
        ])
        turns = local_turns(mic, system, PAS)
        assert len(turns) == 1

    def test_a_real_silence_separates_two_turns(self) -> None:
        # 1,5 s : la personne a fini, quelqu'un d'autre a parlé entre-temps.
        mic, system = levels([
            (-30, -60, 40), (-60, -60, 60), (-30, -60, 40),
        ])
        assert len(local_turns(mic, system, PAS)) == 2

    def test_a_lone_yes_is_dropped(self) -> None:
        # 0,5 s : un acquiescement. Les garder ferait des centaines de tours.
        mic, system = levels([(-60, -60, 40), (-30, -60, 20), (-60, -60, 40)])
        assert local_turns(mic, system, PAS) == []

    def test_a_short_sentence_is_kept(self) -> None:
        mic, system = levels([(-60, -60, 40), (-30, -60, 40), (-60, -60, 40)])
        assert len(local_turns(mic, system, PAS)) == 1


class TestWhatMustNotBreak:
    def test_series_of_different_lengths_do_not_crash(self) -> None:
        mic = [-30.0] * 100
        system = [-60.0] * 40
        turns = local_turns(mic, system, PAS)
        assert turns and turns[0].end <= 40 * PAS

    def test_an_empty_input_gives_no_turn(self) -> None:
        assert local_turns([], [], PAS) == []

    def test_a_step_of_zero_is_refused(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="pas"):
            local_turns([-30.0], [-60.0], 0.0)

    def test_speech_running_to_the_end_is_closed(self) -> None:
        mic, system = levels([(-60, -60, 40), (-30, -60, 60)])
        turns = local_turns(mic, system, PAS)
        assert len(turns) == 1
        assert turns[0].end == 100 * PAS


class TestDroppingTheDuplicates:
    def test_a_remote_turn_covered_by_a_local_one_disappears(self) -> None:
        # La segmentation ne voit que la boucle système, mais un participant qui
        # parle en même temps laisse un tour à cheval. Compter les deux ferait
        # deux personnes là où une tient la parole.
        distants = [Span(10.0, 14.0)]
        local_spans = [Span(9.0, 15.0)]
        assert remove(distants, local_spans) == []

    def test_an_independent_remote_turn_is_kept(self) -> None:
        distants = [Span(30.0, 40.0)]
        local_spans = [Span(9.0, 15.0)]
        assert remove(distants, local_spans) == distants

    def test_a_mere_partial_overlap_removes_nothing(self) -> None:
        # Un quart recouvert : les deux ont parlé, on garde les deux.
        distants = [Span(10.0, 20.0)]
        local_spans = [Span(18.0, 22.0)]
        assert remove(distants, local_spans) == distants

    def test_with_no_local_turn_nothing_changes(self) -> None:
        distants = [Span(1.0, 2.0), Span(3.0, 4.0)]
        assert remove(distants, []) == distants


class TestWhoIsSpeaking:
    """Ce que l'interface affiche pendant la réunion, sans consulter un modèle."""

    def test_silence(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-70, -70) is WhoSpeaks.NOBODY

    def test_you_alone(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-30, -70) is WhoSpeaks.YOU

    def test_the_others_alone(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-70, -25) is WhoSpeaks.THE_OTHERS

    def test_a_real_overlap(self) -> None:
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-20, -35) is WhoSpeaks.BOTH

    def test_the_mic_hearing_the_speakers_again_is_not_you(self) -> None:
        # Écoute par haut-parleurs : les deux canaux sont actifs, mais le micro
        # ne domine pas. Afficher « les deux » ferait clignoter l'interface à
        # chaque phrase des autres.
        from greffier.domain.channels import WhoSpeaks, who_speaks

        assert who_speaks(-28, -25) is WhoSpeaks.THE_OTHERS


class TestInTheRoomAgainstOnACall:
    """La provenance identifie quelqu'un en visio, personne autour d'une table.

    Un portable posé au milieu d'une table n'a rien dans sa boucle système :
    tous les participants parlent dans le même micro. Appliquer quand même la
    séparation par canal en faisait **une seule voix**, celle de la personne qui
    enregistrait. Mesuré : trois locuteurs ramenés à une étiquette « moi ».
    """

    def test_on_a_call_the_local_voice_stands_out(self) -> None:
        # Le micro domine la boucle : c'est la personne qui enregistre.
        mic, system = levels([(-30, -60, 60)])
        assert local_turns(mic, system, PAS)

    def test_a_silent_loopback_proves_no_local_speech(self) -> None:
        # Autour d'une table, la boucle est à -240 dB en permanence : chaque
        # trame de parole « domine » donc la boucle, et tout deviendrait local.
        # C'est à l'adaptateur de ne pas appeler cette fonction dans ce cas,
        # mais le calcul lui-même doit rester lisible pour qui le relit.
        mic, system = levels([(-25, -240, 80)])
        turns = local_turns(mic, system, PAS)
        assert turns, "le calcul reste juste : c'est son usage qui doit être conditionné"


class TestACallOrATable:
    """Reconnaître une visio d'une réunion tenue autour d'une table.

    Premier essai raté, et il a coûté un compte rendu : tester si la boucle
    système est non nulle. Sur une réunion de table réelle elle relevait -53 dB,
    du son y ayant fui, et conclure « visio » attribuait les trente minutes à la
    personne qui enregistrait.

    Ce qui tranche est relatif : en visio les autres dominent le micro une bonne
    part du temps, puisqu'ils passent par les haut-parleurs. Mesuré, 57,7 % des
    trames sur une visio d'une heure, 0,0 % sur une réunion de table.
    """

    def test_a_video_call_is_recognised(self) -> None:
        from greffier.domain.channels import over_video

        # Les autres parlent la moitié du temps.
        mic, system = levels([(-50, -30, 100), (-30, -60, 100)])
        assert over_video(mic, system)

    def test_a_meeting_round_a_table_is_not_taken_for_a_call(self) -> None:
        from greffier.domain.channels import over_video

        # Tout le monde passe par le micro, la boucle ne porte rien.
        mic, system = levels([(-35, -240, 200)])
        assert not over_video(mic, system)

    def test_a_loopback_that_hisses_without_speech_stays_a_room(
        self,
    ) -> None:
        # Le cas qui a échoué : une boucle à -53 dB, jamais dominante.
        from greffier.domain.channels import over_video

        mic, system = levels([(-35, -53, 200)])
        assert not over_video(mic, system)

    def test_one_remote_word_does_not_make_a_call(self) -> None:
        # Une notification, un son joué en séance : deux trames sur deux cents.
        from greffier.domain.channels import over_video

        mic, system = levels([(-35, -240, 198), (-50, -30, 2)])
        assert not over_video(mic, system)

    def test_an_empty_input_concludes_no_call(self) -> None:
        from greffier.domain.channels import over_video

        assert not over_video([], [])


class TestSubtractingSpans:
    """Ôter d'un passage ce que le canal attribue à la personne au micro.

    Le cas mesuré : la transcription coupe à la phrase, pas au changement de
    locuteur. Un extrait de 1,5 s portant 0,6 s de voix locale donnait une
    empreinte mêlée, et la même personne devenait deux participants.
    """

    def test_a_slice_in_the_middle_cuts_in_two(self) -> None:
        remainders = subtract(Span(0, 10), [Span(4, 6)])
        assert remainders == [Span(0, 4), Span(6, 10)]

    def test_a_slice_at_the_head_shortens_the_start(self) -> None:
        assert subtract(Span(13.2, 14.7), [Span(9.5, 13.8)]) == [
            Span(13.8, 14.7)
        ]

    def test_a_fully_covered_passage_leaves_nothing(self) -> None:
        assert subtract(Span(2, 4), [Span(0, 10)]) == []

    def test_a_disjoint_passage_stays_whole(self) -> None:
        assert subtract(Span(0, 3), [Span(5, 8)]) == [Span(0, 3)]

    def test_several_slices_subtract_one_after_another(self) -> None:
        remainders = subtract(Span(0, 12), [Span(2, 4), Span(7, 9)])
        assert remainders == [Span(0, 2), Span(4, 7), Span(9, 12)]

    def test_with_nothing_to_remove_the_span_is_unchanged(self) -> None:
        assert subtract(Span(0, 5), []) == [Span(0, 5)]
