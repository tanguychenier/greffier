"""Les pièges déjà rencontrés, rejoués à travers la vraie chaîne.

`outils/fabriquer_cas_difficiles.py` fabrique un enregistrement par défaut
constaté sur une vraie réunion ou rendu possible par la conception. Ce fichier
les fait passer par la vraie chaîne — segmentation, reconnaissance, attribution
des noms — plutôt que par des doublures, pour prouver que le défaut reste
corrigé.

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
from greffier.application.name_voice import voices_to_name
from greffier.application.process import Chain
from greffier.application.process import _as_stored_meeting as depuis_resultat

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


def _fabriquer_cas(name: str, tmp_path_factory) -> Path:
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    from fabriquer_cas_difficiles import CAS
    from fabriquer_reunion import fabriquer

    voice, dialogue = CAS[name]
    destination = tmp_path_factory.mktemp("audio") / f"cas-{name}.wav"
    return fabriquer(destination, voice=voice, dialogue=dialogue)


def _process(config: Config, audio: Path):
    from greffier.wiring import wire_up

    config.minutes.engine = "aucun"
    chain: Chain = wire_up(config)
    chain.writer = None
    return chain.run_chain(audio, send=False)


@pytest.fixture(scope="session")
def resultat_trois_voix(config: Config, tmp_path_factory):
    """Trois locuteurs, dont deux proches en timbre.

    La segmentation ne doit ni fusionner deux d'entre eux par accident, ni
    sur-découper une même personne en plusieurs voix.
    """
    audio = _fabriquer_cas("trois-voix", tmp_path_factory)
    return _process(config, audio)


class TestTroisVoix:
    def test_les_trois_voix_sont_distinguees(self, resultat_trois_voix):
        """Trois voix distinctes, chacune avec plusieurs secondes de matière —
        pas deux (fusion à tort) ni davantage (sur-découpage résiduel)."""
        temps = resultat_trois_voix.speaking_time()
        assert len(temps) == 3
        assert all(duration >= 5.0 for duration in temps.values())

    def test_les_deux_auto_presentations_sont_retrouvees(self, resultat_trois_voix):
        """Jacques et Amélie se présentent ; la troisième voix reste sans nom
        plutôt que d'hériter de celui d'un autre — un « merci Amélie » dit
        juste après le tour de la troisième personne est un piège volontaire
        du fixture (`outils/fabriquer_cas_difficiles.py`), à ne jamais
        affirmer sans plus de matière."""
        assert set(resultat_trois_voix.names.values()) == {"Jacques", "Amélie"}
        assert len(resultat_trois_voix.names) == 2


@pytest.fixture(scope="session")
def resultat_proposition_breve(config: Config, tmp_path_factory):
    """C parle une seule fois, brièvement, et n'est jamais nommée par
    elle-même : seul un renvoi juste après son tour la vise, un indice trop
    faible pour être affirmé — mais qui ne doit pas se perdre pour autant."""
    audio = _fabriquer_cas("proposition-breve", tmp_path_factory)
    return _process(config, audio)


class TestPropositionBreve:
    def test_la_proposition_existe_dans_le_resultat(self, resultat_proposition_breve):
        """La donnée n'est jamais perdue : le renvoi produit bien une
        proposition, jamais une certitude — un seul indice ne suffit pas."""
        temps = resultat_proposition_breve.speaking_time()
        voix_breve = min(temps, key=lambda v: temps[v])
        assert temps[voix_breve] < 10.0
        assert resultat_proposition_breve.propositions.get(voix_breve) is not None
        assert voix_breve not in resultat_proposition_breve.names

    def test_la_proposition_survit_jusqu_a_l_ecran_de_nommage(self, resultat_proposition_breve):
        """Le défaut corrigé : `voix_a_nommer` ne doit plus taire une voix
        courte qui porte une proposition détectée."""
        meeting = depuis_resultat(resultat_proposition_breve, duration=60.0)
        voix_breve = min(
            resultat_proposition_breve.speaking_time(),
            key=lambda v: resultat_proposition_breve.speaking_time()[v],
        )
        input = next(v for v in voices_to_name(meeting) if v.voice == voix_breve)
        assert input.proposition is not None
