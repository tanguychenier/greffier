"""La banque de voix, d'une réunion à l'autre — le cœur du besoin.

Deux réunions synthétisées avec les mêmes voix. Des prénoms sont prononcés dans
la première, aucun dans la seconde. Si la seconde nomme quand même les
participants, c'est nécessairement par reconnaissance vocale : c'est toute la
promesse de l'outil, et elle est vérifiée ici de bout en bout.
"""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.adapters.store_files import FileStore
from greffier.adapters.voice_bank_files import FileVoiceBank
from greffier.application.name_voice import Naming, voices_to_name
from greffier.application.process import _as_stored_meeting as depuis_resultat

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "outils"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def atelier(tmp_path_factory):
    """Un poste vierge : banque vide, aucune réunion connue."""
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    if not shutil.which("whisper-cli"):
        pytest.skip("whisper.cpp absent")

    config = Config()
    diarisation = config.paths.models / "diarisation"
    if not (diarisation / "nemo_en_titanet_large.onnx").exists():
        pytest.skip("modèles absents — lance outils/installer.py")

    racine = tmp_path_factory.mktemp("poste")
    config.paths.data = racine
    config.minutes.engine = "aucun"

    from fabriquer_reunion import DIALOGUE_SANS_NOMS, fabriquer

    premiere = fabriquer(racine / "reunion-1.wav")
    seconde = fabriquer(racine / "reunion-2.wav", dialogue=DIALOGUE_SANS_NOMS)
    return config, premiere, seconde


def process(config, audio):
    from greffier.wiring import wire_up

    chaine = wire_up(config)
    chaine.writer = None
    outcome = chaine.run_chain(audio, send=False)
    duration = outcome.turns[-1].span.end if outcome.turns else 0.0
    store = FileStore(config.paths.data / "reunions")
    store.record(depuis_resultat(outcome, duration))
    return outcome


class TestReconnaissanceEntreReunions:
    def test_le_parcours_complet(self, atelier):
        """Première réunion → nommage → seconde réunion reconnue toute seule."""
        config, premiere, seconde = atelier
        bank = FileVoiceBank(config.paths.voice_bank)
        store = FileStore(config.paths.data / "reunions")

        # 1. La première réunion : les prénoms viennent de ce qui est dit.
        outcome = process(config, premiere)
        assert set(outcome.names.values()) == {"Jacques", "Sandy"}

        # 2. L'utilisateur valide — c'est lui qui décide, rien n'entre en banque
        #    sans ce geste.
        from greffier.adapters.voiceprints_titanet import TitaNetExtractor

        namer = Naming(
            store=store,
            bank=bank,
            extractor=TitaNetExtractor(
                config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
            ),
        )
        for voice, name in outcome.names.items():
            namer.name_voice(premiere.stem, voice, name)
        assert {p.name for p in bank.people()} == {"Jacques", "Sandy"}

        # 3. La seconde réunion ne prononce aucun prénom.
        second_resultat = process(config, seconde)
        transcription = " ".join(r.text for r in second_resultat.utterances)
        assert "Jacques" not in transcription and "Sandy" not in transcription

        # 4. Et pourtant les deux sont nommés : cela ne peut venir que de la voix.
        assert set(second_resultat.names.values()) == {"Jacques", "Sandy"}

    def test_la_banque_ne_nomme_pas_n_importe_qui(self, atelier, tmp_path):
        """Une banque contenant une voix étrangère ne doit rien reconnaître."""
        config, _, seconde = atelier
        from greffier.domain.voiceprints import normalise
        from greffier.wiring import wire_up

        etrangere = FileVoiceBank(tmp_path / "banque-etrangere")
        etrangere.record("Personne d'autre", normalise([1.0] + [0.0] * 191))

        chaine = wire_up(config)
        chaine.bank = etrangere
        chaine.writer = None
        outcome = chaine.run_chain(seconde, send=False)
        assert "Personne d'autre" not in outcome.names.values()

    def test_les_voix_a_nommer_sont_presentees_avec_un_extrait(self, atelier):
        """Le parcours réel : écouter dix secondes, taper un nom."""
        config, premiere, _ = atelier
        meeting = FileStore(config.paths.data / "reunions").read(premiere.stem)
        candidates = voices_to_name(meeting)
        assert len(candidates) == 2
        assert all(c.extrait is not None and c.extrait.duration >= 3 for c in candidates)
        # De la plus bavarde à la moins : on nomme d'abord qui compte le plus.
        assert candidates[0].duration >= candidates[1].duration
