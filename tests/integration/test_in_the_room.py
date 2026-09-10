"""Une réunion tenue autour d'une table, de bout en bout.

Le cas n'avait jamais été éprouvé : tout ce qui avait servi jusqu'ici était une
visio, où le canal identifie avec certitude la personne qui enregistre. Autour
d'une table, **tout le monde parle dans le même micro** : la provenance ne
désigne plus personne, et il ne reste que la segmentation et la banque de voix.

L'audio est synthétisé — trois voix du système, un dialogue fictif — et assemblé
en stéréo comme le rend le périphérique d'enregistrement : le micro sur le canal
0, la boucle système sur le canal 1 avec la fuite mesurée sur la vraie réunion
de table (-53 dB au lieu du silence attendu). C'est cette fuite qui piégeait le
verdict, quand une boucle non nulle suffisait à conclure « visio ».

Ce que ce test **ne** mesure pas : la qualité de la transcription. Les voix de
synthèse rendent un texte approximatif — mesuré, la même réplique rend
« L.S. Dominé, Depuis, I.S.W.A. » d'une voix à l'autre — et un test qui les
comparerait mesurerait « say », pas Greffier. Il vérifie donc ce qui ne dépend
pas du timbre : le verdict de canal, le nombre de voix, et le refus de trancher.

    pytest -m integration
"""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.process import Chain
from greffier.domain.channels import LOCAL_VOICE

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))

pytestmark = pytest.mark.integration


def models_present(config: Config) -> bool:
    diarisation = config.paths.models / "diarisation"
    return (
        (config.paths.models / "ggml-large-v3-turbo.bin").exists()
        and (diarisation / "nemo_en_titanet_large.onnx").exists()
        and (diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").exists()
    )


@pytest.fixture(scope="session")
def config() -> Config:
    configuration = Config()
    if not models_present(configuration):
        pytest.skip("modèles absents — lance tools/install.py")
    if not shutil.which("whisper-cli"):
        pytest.skip("whisper.cpp absent")
    return configuration


@pytest.fixture(scope="session")
def table(tmp_path_factory) -> Path:
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    from make_meeting import make_in_the_room

    return make_in_the_room(tmp_path_factory.mktemp("audio") / "table.wav")


@pytest.fixture(scope="session")
def outcome(config: Config, table: Path):
    from greffier.wiring import wire_up

    config.minutes.engine = "aucun"
    chain: Chain = wire_up(config)
    chain.writer = None
    return chain.run_chain(table, send=False)


class TestVerdictDeCanal:
    def test_la_fuite_dans_la_boucle_ne_fait_pas_conclure_visio(self, table: Path):
        import soundfile as sf

        from greffier.adapters.channels_file import levels_per_frame
        from greffier.domain.channels import over_video

        data, frequency = sf.read(table, dtype="float32", always_2d=True)
        assert data.shape[1] == 2, "le fichier d'essai doit être stéréo"
        mic = levels_per_frame(data[:, 0], frequency)
        boucle = levels_per_frame(data[:, 1], frequency)
        assert max(boucle) < -45.0, "la fuite doit rester sous le plancher de bruit"
        assert not over_video(mic, boucle)

    def test_le_micro_sert_de_reference_aux_deux_canaux(self, table: Path):
        """En présentiel, la boucle n'a rien à apporter : on ne s'en sert plus."""
        import numpy as np
        import soundfile as sf

        from greffier.adapters.channels_file import separer_canaux

        data, frequency = sf.read(table, dtype="float32", always_2d=True)
        channels = separer_canaux(data, frequency)
        assert channels.distante is False
        assert np.array_equal(channels.system, channels.mic)

    def test_aucun_passage_n_est_declare_local(self, table: Path):
        """Le canal ne désigne personne : mieux vaut rien que « Toi » à tort.

        Sur une visio, ces passages sont la seule attribution qui ne se trompe
        jamais. Autour d'une table, les retenir ferait de tous les participants
        une seule et même personne — mesuré : trois locuteurs ramenés à une
        étiquette « moi ».
        """
        from greffier.adapters.channels_file import FileChannelReader

        assert FileChannelReader().local_passages(table) == []


class TestChaineEnPresentiel:
    def test_la_reunion_est_transcrite(self, outcome):
        assert outcome.words > 60, "la transcription a perdu l'essentiel du dialogue"

    def test_personne_n_est_etiquete_comme_la_voix_locale(self, outcome):
        """Le défaut que le présentiel pouvait faire apparaître, en toutes lettres."""
        assert LOCAL_VOICE not in outcome.speaking_time()

    def test_les_participants_ne_sont_pas_fondus_en_une_seule_voix(self, outcome):
        """Trois personnes autour d'une table restent plusieurs voix.

        Le compte exact dépend du timbre des voix de synthèse — deux d'entre
        elles se ressemblent assez pour être recollées — donc on vérifie qu'on
        n'a ni une seule voix, ni un participant par réplique.
        """
        significatives = outcome.significant_voices()
        assert 2 <= len(significatives) <= len(outcome.utterances)

    def test_les_fragments_ne_comptent_pas_comme_des_participants(self, outcome):
        assert all(duration >= 10 for duration in outcome.significant_voices().values())

    def test_l_auto_presentation_reste_juste_sans_le_secours_du_canal(self, outcome):
        """« moi c'est Jacques » désigne celui qui parle, canal ou pas."""
        assert outcome.name_of(outcome.utterances[0].voice) == "Jacques"

    def test_aucune_phrase_a_cheval_n_est_attribuee(self, outcome):
        """Une phrase que deux voix se partagent ne doit désigner personne.

        C'est la règle de `domaine/attribution.py`, éprouvée ici sur la vraie
        chaîne : rien ne garantit que la découpe de whisper tombe sur un
        changement de locuteur, et le présentiel n'a pas le canal pour rattraper.
        """
        from greffier.domain.attribution import PART_MINIMALE, time_per_voice

        for utterance in outcome.utterances:
            cumuls = time_per_voice(utterance.span, outcome.turns)
            if not cumuls:
                continue
            part = max(cumuls.values()) / sum(cumuls.values())
            if part < PART_MINIMALE:
                assert utterance.voice is None, (
                    f"« {utterance.text[:40]} » est partagée à {part:.0%} "
                    "et se voit pourtant attribuer une voix"
                )
