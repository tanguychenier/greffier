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
sys.path.insert(0, str(RACINE / "tools"))

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
        pytest.skip("modèles absents — lance tools/install.py")

    root = tmp_path_factory.mktemp("poste")
    config.paths.data = root
    config.minutes.engine = "aucun"

    from make_meeting import DIALOGUE_SANS_NOMS, fabriquer

    premiere = fabriquer(root / "reunion-1.wav")
    seconde = fabriquer(root / "reunion-2.wav", dialogue=DIALOGUE_SANS_NOMS)
    return config, premiere, seconde


def process(config, audio):
    from greffier.wiring import wire_up

    chain = wire_up(config)
    chain.writer = None
    outcome = chain.run_chain(audio, send=False)
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

        chain = wire_up(config)
        chain.bank = etrangere
        chain.writer = None
        outcome = chain.run_chain(seconde, send=False)
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


@pytest.mark.integration
class TestSeparerApresLaReunionDeBoutEnBout:
    """Le geste complet : réunir, écrire, relire, séparer, réécrire.

    Ce qui manquait : le fil du direct savait revenir en arrière, la chaîne
    d'après réunion non. Deux personnes réunies à tort le restaient jusqu'au
    compte rendu, et le compte rendu annonçait un participant de moins.

    Ce test passe par le vrai dépôt de fichiers, pas par une doublure : c'est
    la persistance qui manquait, et c'est elle qu'il faut éprouver.
    """

    def _reunion(self, tmp_path):
        from datetime import UTC, datetime

        from greffier.domain.meeting import StoredMeeting
        from greffier.domain.models import Span, SpeakerTurn, Utterance

        return StoredMeeting(
            identifier="2026-09-10_10h10_reunion",
            audio=tmp_path / "r.wav",
            processed_at=datetime.now(UTC),
            duration=120.0,
            utterances=[
                Utterance(Span(0, 40), "on cale la recette jeudi", "v1"),
                Utterance(Span(50, 90), "le devis part demain matin", "v2"),
            ],
            turns=[SpeakerTurn(Span(0, 40), "v1"), SpeakerTurn(Span(50, 90), "v2")],
            names={"v1": "Tanguy", "v2": "Pascal"},
            propositions={},
            warnings=[],
        )

    def test_le_cycle_complet(self, tmp_path):
        from greffier.adapters.store_files import FileStore

        magasin = FileStore(tmp_path / "reunions")
        detail = self._reunion(tmp_path)
        detail.join_into("v2", "v1")
        magasin.record(detail)

        # Ce que le compte rendu aurait annoncé : une seule personne.
        relue = magasin.read("2026-09-10_10h10_reunion")
        assert list(relue.names.values()) == ["Tanguy"]
        assert {t.voice for t in relue.turns} == {"v1"}

        # Le geste qui manquait, et il survit à l'écriture.
        assert relue.can_split("v1")
        relue.split("v1")
        magasin.record(relue)

        finale = magasin.read("2026-09-10_10h10_reunion")
        assert sorted(finale.names.values()) == ["Pascal", "Tanguy"]
        assert {t.voice for t in finale.turns} == {"v1", "v2"}
        assert {u.voice for u in finale.utterances} == {"v1", "v2"}
        assert not finale.can_split("v1"), "défaite une fois, pas deux"

    def test_le_temps_de_parole_revient_a_chacun(self, tmp_path):
        """C'est ce que le compte rendu annonce : qui a parlé combien."""
        detail = self._reunion(tmp_path)
        detail.join_into("v2", "v1")
        assert detail.speaking_time()["v1"] == 80.0
        detail.split("v1")
        temps = detail.speaking_time()
        assert temps["v1"] == 40.0
        assert temps["v2"] == 40.0
