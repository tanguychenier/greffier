"""Ce que les canaux d'un enregistrement disent de la provenance du son.

Ces cas vivaient dans les tests des périphériques, et devaient forcer une
instance de diariseur sans l'initialiser pour atteindre une méthode privée. La
règle ayant son propre module, ils s'écrivent maintenant directement — et le
direct s'appuie sur le même code que le traitement final, ce qui est le point :
la fenêtre ne doit pas afficher un locuteur que le compte rendu contredira.
"""

from __future__ import annotations

import numpy as np

from greffier.adapters.channels_file import (
    FileChannelReader,
    levels_per_frame,
    separer_canaux,
)


def signal(channels: list[list[float]]) -> np.ndarray:
    return np.array(channels, dtype="float32").T


class TestVisioOuPresentiel:
    def test_a_loopback_that_dominates_means_a_call(self) -> None:
        # Les autres passent par les haut-parleurs et couvrent le micro : c'est
        # ce qui distingue une visio, pas la simple présence d'un signal.
        fort, faible = [0.2] * 16000, [0.001] * 16000
        channels = separer_canaux(signal([faible, fort, fort]))
        assert channels.distante
        assert channels.mic is not None

    def test_a_loopback_alive_but_never_dominant_stays_a_room(self) -> None:
        # Le cas qui avait échoué : une boucle à -53 dB, du son y ayant fui,
        # mais qui ne couvre jamais le micro. Conclure « visio » attribuait
        # trente minutes de réunion à la seule personne qui enregistrait.
        channels = separer_canaux(signal([[0.2] * 16000, [0.002] * 16000, [0.002] * 16000]))
        assert not channels.distante
        # Et c'est le micro qu'il faut segmenter, là où tout le monde parle.
        assert float(abs(channels.system).max()) > 0.1

    def test_une_boucle_muette_signifie_presentiel(self) -> None:
        # Le portable posé au milieu d'une table.
        channels = separer_canaux(signal([[0.1] * 16000, [0.0] * 16000, [0.0] * 16000]))
        assert not channels.distante
        assert float(abs(channels.system).max()) > 0

    def test_a_silent_channel_does_not_divide_the_others_amplitude(self) -> None:
        channels = separer_canaux(signal([[0.001] * 16000, [0.0] * 16000, [0.2] * 16000]))
        assert channels.distante
        assert float(abs(channels.system).max()) > 0.15

    def test_a_mono_file_allows_no_separation(self) -> None:
        channels = separer_canaux(signal([[0.1] * 100]))
        assert channels.mic is None and not channels.distante


class TestAVideoCallStaysAVideoCall:
    """Le verdict se lit sur l'ensemble de l'audio, pas sur dix secondes.

    Le défaut mesuré : sur une tranche où seule la personne au micro parle,
    aucune boucle ne domine, donc « présentiel » — et sa voix, cessant d'être
    désignée par le canal, devenait un participant distant de plus.
    """

    def test_the_forced_mode_wins_over_what_the_slice_says(self) -> None:
        seule_ma_voix = signal([[0.2] * 16000, [0.0] * 16000, [0.0] * 16000])
        assert not separer_canaux(seule_ma_voix).distante
        assert separer_canaux(seule_ma_voix, distante=True).distante

    def test_a_silent_loopback_forced_to_a_call_leaves_the_floor_to_the_mic(self) -> None:
        # C'est ce qui permet de continuer à afficher « Toi » quand personne
        # d'autre ne parle pendant une tranche entière.
        channels = separer_canaux(
            signal([[0.2] * 16000, [0.0] * 16000, [0.0] * 16000]), distante=True
        )
        assert channels.mic is not None
        assert float(abs(channels.system).max()) == 0.0

    def test_the_reader_keeps_the_verdict_from_one_slice_to_the_next(
        self, tmp_path
    ) -> None:
        import soundfile as sf

        player = FileChannelReader()
        assert not player.distante
        # Une tranche de visio : la boucle couvre le micro.
        visio = tmp_path / "visio.wav"
        sf.write(visio, signal([[0.001] * 16000, [0.2] * 16000, [0.2] * 16000]), 16000)
        player.local_passages(visio)
        assert player.distante
        # La tranche suivante ne porte que ma voix : le verdict tient, et ce
        # passage m'est attribué au lieu de créer une voix distante.
        seul = tmp_path / "seul.wav"
        sf.write(seul, signal([[0.2] * 32000, [0.0] * 32000, [0.0] * 32000]), 16000)
        assert player.local_passages(seul) != []


class TestNiveaux:
    def test_digital_silence_does_not_give_minus_infinity(self) -> None:
        levels = levels_per_frame(np.zeros(16000, dtype="float32"), 16000)
        assert levels and all(n < -200 for n in levels)

    def test_a_signal_too_short_for_a_frame_gives_nothing(self) -> None:
        assert levels_per_frame(np.zeros(10, dtype="float32"), 16000) == []


class TestReadingTheSetting:
    def test_an_unreadable_file_does_not_stop_the_meeting(self, tmp_path) -> None:
        # Une tranche découpée pendant l'écriture peut arriver tronquée : le
        # direct affiche alors la phrase sans « Toi », il ne s'arrête pas.
        absent = tmp_path / "rien.wav"
        assert FileChannelReader().local_passages(absent) == []
