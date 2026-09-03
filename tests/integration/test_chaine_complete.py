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

from greffier.application.traiter import Traitement
from greffier.config import Config

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "outils"))

pytestmark = pytest.mark.integration


def modeles_presents(config: Config) -> bool:
    diarisation = config.chemins.modeles / "diarisation"
    return (
        (config.chemins.modeles / "ggml-large-v3-turbo.bin").exists()
        and (diarisation / "nemo_en_titanet_large.onnx").exists()
        and (diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").exists()
    )


@pytest.fixture(scope="session")
def config() -> Config:
    configuration = Config()
    if not modeles_presents(configuration):
        pytest.skip("modèles absents — lance outils/installer.py")
    if not shutil.which("whisper-cli"):
        pytest.skip("whisper.cpp absent")
    return configuration


@pytest.fixture(scope="session")
def reunion(tmp_path_factory) -> Path:
    """Fabrique une fois la fausse réunion, réutilisée par tous les tests."""
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    from fabriquer_reunion import fabriquer

    return fabriquer(tmp_path_factory.mktemp("audio") / "reunion.wav")


@pytest.fixture(scope="session")
def resultat(config: Config, reunion: Path):
    """Passe la fausse réunion dans la vraie chaîne, sans rédaction.

    Le rédacteur est débranché : appeler Claude ou Ollama depuis un test le
    rendrait lent, coûteux et dépendant du réseau. Ce que ce test doit prouver,
    c'est que l'audio arrive jusqu'à une transcription attribuée.
    """
    from greffier.composition import assembler

    config.compte_rendu.moteur = "aucun"
    chaine: Traitement = assembler(config)
    chaine.redacteur = None
    return chaine.executer(reunion, envoyer=False)


class TestChaineReelle:
    def test_l_audio_synthetise_est_bien_transcrit(self, resultat):
        assert resultat.mots > 60, "la transcription a perdu l'essentiel du dialogue"

    def test_les_deux_voix_sont_separees(self, resultat):
        """Cinq répliques alternées, deux voix : ni fusion, ni sur-découpage."""
        assert len(resultat.voix_significatives()) == 2

    def test_les_fragments_ne_comptent_pas_comme_des_participants(self, resultat):
        significatives = resultat.voix_significatives()
        assert all(duree >= 10 for duree in significatives.values())

    def test_les_deux_prenoms_sont_retrouves(self, resultat):
        """Le cœur du besoin : « Jacques » et « Sandy », pas « Personne 1 ».

        Chaque prénom est prononcé deux fois, de deux façons différentes — le
        cumul d'indices doit suffire à trancher sans demander à l'utilisateur.
        """
        assert set(resultat.noms.values()) == {"Jacques", "Sandy"}

    def test_chaque_prenom_va_a_une_voix_differente(self, resultat):
        assert len(set(resultat.noms)) == 2

    def test_l_auto_presentation_gagne_sur_le_reste(self, resultat):
        """Celui qui dit « moi c'est Jacques » est Jacques, quoi qu'il arrive."""
        premiere = resultat.repliques[0]
        assert resultat.nom_de(premiere.voix) == "Jacques"

    def test_un_enregistrement_mono_ne_declenche_pas_de_fausse_alerte(self, resultat):
        """Un fichier à un seul canal n'a pas de second canal manquant.

        L'alerte « aucun son système capté » n'a de sens que sur un
        enregistrement à deux canaux, où l'un des deux est effectivement vide.
        La déclencher sur du mono reviendrait à crier au loup à chaque
        enregistrement fait au simple micro.
        """
        assert resultat.avertissements == []

    def test_la_transcription_rendue_est_attribuee_et_horodatee(self, resultat):
        from greffier.application.restituer import rendre_transcription

        texte = rendre_transcription(resultat)
        assert "[Jacques]" in texte and "[Sandy]" in texte
        assert "00:0" in texte
        assert "Personne" not in texte, "aucune voix ne devrait rester anonyme"
