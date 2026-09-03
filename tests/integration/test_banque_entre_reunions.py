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

from greffier.adaptateurs.banque_fichiers import BanqueFichiers
from greffier.adaptateurs.depot_fichiers import DepotFichiers, depuis_resultat
from greffier.application.nommer import Nommage, voix_a_nommer
from greffier.config import Config

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
    diarisation = config.chemins.modeles / "diarisation"
    if not (diarisation / "nemo_en_titanet_large.onnx").exists():
        pytest.skip("modèles absents — lance outils/installer.py")

    racine = tmp_path_factory.mktemp("poste")
    config.chemins.donnees = racine
    config.compte_rendu.moteur = "aucun"

    from fabriquer_reunion import DIALOGUE_SANS_NOMS, fabriquer

    premiere = fabriquer(racine / "reunion-1.wav")
    seconde = fabriquer(racine / "reunion-2.wav", dialogue=DIALOGUE_SANS_NOMS)
    return config, premiere, seconde


def traiter(config, audio):
    from greffier.composition import assembler

    chaine = assembler(config)
    chaine.redacteur = None
    resultat = chaine.executer(audio, envoyer=False)
    duree = resultat.tours[-1].intervalle.fin if resultat.tours else 0.0
    depot = DepotFichiers(config.chemins.donnees / "reunions")
    depot.enregistrer(depuis_resultat(resultat, duree))
    return resultat


class TestReconnaissanceEntreReunions:
    def test_le_parcours_complet(self, atelier):
        """Première réunion → nommage → seconde réunion reconnue toute seule."""
        config, premiere, seconde = atelier
        banque = BanqueFichiers(config.chemins.banque_de_voix)
        depot = DepotFichiers(config.chemins.donnees / "reunions")

        # 1. La première réunion : les prénoms viennent de ce qui est dit.
        resultat = traiter(config, premiere)
        assert set(resultat.noms.values()) == {"Jacques", "Sandy"}

        # 2. L'utilisateur valide — c'est lui qui décide, rien n'entre en banque
        #    sans ce geste.
        from greffier.adaptateurs.empreintes_titanet import ExtracteurTitaNet

        nommeur = Nommage(
            depot=depot,
            banque=banque,
            extracteur=ExtracteurTitaNet(
                config.chemins.modeles / "diarisation" / "nemo_en_titanet_large.onnx"
            ),
        )
        for voix, nom in resultat.noms.items():
            nommeur.nommer(premiere.stem, voix, nom)
        assert {p.nom for p in banque.personnes()} == {"Jacques", "Sandy"}

        # 3. La seconde réunion ne prononce aucun prénom.
        second_resultat = traiter(config, seconde)
        transcription = " ".join(r.texte for r in second_resultat.repliques)
        assert "Jacques" not in transcription and "Sandy" not in transcription

        # 4. Et pourtant les deux sont nommés : cela ne peut venir que de la voix.
        assert set(second_resultat.noms.values()) == {"Jacques", "Sandy"}

    def test_la_banque_ne_nomme_pas_n_importe_qui(self, atelier, tmp_path):
        """Une banque contenant une voix étrangère ne doit rien reconnaître."""
        config, _, seconde = atelier
        from greffier.composition import assembler
        from greffier.domaine.empreintes import normaliser

        etrangere = BanqueFichiers(tmp_path / "banque-etrangere")
        etrangere.enregistrer("Personne d'autre", normaliser([1.0] + [0.0] * 191))

        chaine = assembler(config)
        chaine.banque = etrangere
        chaine.redacteur = None
        resultat = chaine.executer(seconde, envoyer=False)
        assert "Personne d'autre" not in resultat.noms.values()

    def test_les_voix_a_nommer_sont_presentees_avec_un_extrait(self, atelier):
        """Le parcours réel : écouter dix secondes, taper un nom."""
        config, premiere, _ = atelier
        reunion = DepotFichiers(config.chemins.donnees / "reunions").lire(premiere.stem)
        candidates = voix_a_nommer(reunion)
        assert len(candidates) == 2
        assert all(c.extrait is not None and c.extrait.duree >= 3 for c in candidates)
        # De la plus bavarde à la moins : on nomme d'abord qui compte le plus.
        assert candidates[0].duree >= candidates[1].duree
