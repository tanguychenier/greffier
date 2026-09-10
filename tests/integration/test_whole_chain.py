"""La chaîne réelle, de bout en bout, sur un vrai fichier audio.

Les tests unitaires vérifient les règles ; celui-ci vérifie qu'elles tiennent
face aux modèles. C'est lui qui a trouvé le défaut que les doublures ne
pouvaient pas voir : whisper fait commencer sa première réplique à 00:00,00
alors que la segmentation ne détecte la parole qu'à 00:00,30, si bien qu'une
auto-présentation tombait entre deux tours de parole et ne désignait personne.

L'audio est **synthétisé** : une vraie réunion contient des échanges de travail
et des voix identifiables, elle ne peut pas servir de jeu d'essai. Deux voix du
système suffisent à produire un fichier réel, passé par exactement le même
chemin que n'importe quel enregistrement.

Lent (transcription comprise) et dépendant des modèles : marqué « integration »,
et ignoré partout où les modèles ne sont pas installés.

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

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "outils"))

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
        pytest.skip("modèles absents — lance outils/installer.py")
    if not shutil.which("whisper-cli"):
        pytest.skip("whisper.cpp absent")
    return configuration


@pytest.fixture(scope="session")
def meeting(tmp_path_factory) -> Path:
    """Fabrique une fois la fausse réunion, réutilisée par tous les tests."""
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    from fabriquer_reunion import fabriquer

    return fabriquer(tmp_path_factory.mktemp("audio") / "reunion.wav")


@pytest.fixture(scope="session")
def outcome(config: Config, meeting: Path):
    """Passe la fausse réunion dans la vraie chaîne, sans rédaction.

    Le rédacteur est débranché : appeler Claude ou Ollama depuis un test le
    rendrait lent, coûteux et dépendant du réseau. Ce que ce test doit prouver,
    c'est que l'audio arrive jusqu'à une transcription attribuée.
    """
    from greffier.wiring import wire_up

    config.minutes.engine = "aucun"
    chain: Chain = wire_up(config)
    chain.writer = None
    return chain.run_chain(meeting, send=False)


class TestChaineReelle:
    def test_l_audio_synthetise_est_bien_transcrit(self, outcome):
        assert outcome.words > 60, "la transcription a perdu l'essentiel du dialogue"

    def test_les_deux_voix_sont_separees(self, outcome):
        """Cinq répliques alternées, deux voix : ni fusion, ni sur-découpage."""
        assert len(outcome.significant_voices()) == 2

    def test_les_fragments_ne_comptent_pas_comme_des_participants(self, outcome):
        significatives = outcome.significant_voices()
        assert all(duration >= 10 for duration in significatives.values())

    def test_les_deux_prenoms_sont_retrouves(self, outcome):
        """Le cœur du besoin : « Jacques » et « Sandy », pas « Personne 1 ».

        Chaque prénom est prononcé deux fois, de deux façons différentes — le
        cumul d'indices doit suffire à trancher sans demander à l'utilisateur.
        """
        assert set(outcome.names.values()) == {"Jacques", "Sandy"}

    def test_chaque_prenom_va_a_une_voix_differente(self, outcome):
        assert len(set(outcome.names)) == 2

    def test_l_auto_presentation_gagne_sur_le_reste(self, outcome):
        """Celui qui dit « moi c'est Jacques » est Jacques, quoi qu'il arrive."""
        premiere = outcome.utterances[0]
        assert outcome.nom_de(premiere.voice) == "Jacques"

    def test_un_enregistrement_mono_ne_declenche_pas_de_fausse_alerte(self, outcome):
        """Un fichier à un seul canal n'a pas de second canal manquant.

        L'alerte « aucun son système capté » n'a de sens que sur un
        enregistrement à deux canaux, où l'un des deux est effectivement vide.
        La déclencher sur du mono reviendrait à crier au loup à chaque
        enregistrement fait au simple micro.
        """
        assert outcome.warnings == []

    def test_la_transcription_rendue_est_attribuee_et_horodatee(self, outcome):
        from greffier.application.render import render_transcript

        text = render_transcript(outcome)
        assert "[Jacques]" in text and "[Sandy]" in text
        assert "00:0" in text
        assert "Personne" not in text, "aucune voix ne devrait rester anonyme"
