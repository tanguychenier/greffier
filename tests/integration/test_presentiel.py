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

from greffier.application.traiter import Traitement
from greffier.config import Config
from greffier.domaine.canaux import VOIX_LOCALE

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
def table(tmp_path_factory) -> Path:
    if platform.system() != "Darwin":
        pytest.skip("la synthèse vocale « say » n'existe que sur macOS")
    from fabriquer_reunion import fabriquer_presentiel

    return fabriquer_presentiel(tmp_path_factory.mktemp("audio") / "table.wav")


@pytest.fixture(scope="session")
def resultat(config: Config, table: Path):
    from greffier.composition import assembler

    config.compte_rendu.moteur = "aucun"
    chaine: Traitement = assembler(config)
    chaine.redacteur = None
    return chaine.executer(table, envoyer=False)


class TestVerdictDeCanal:
    def test_la_fuite_dans_la_boucle_ne_fait_pas_conclure_visio(self, table: Path):
        import soundfile as sf

        from greffier.adaptateurs.canaux_fichier import niveaux_par_trame
        from greffier.domaine.canaux import en_visio

        donnees, frequence = sf.read(table, dtype="float32", always_2d=True)
        assert donnees.shape[1] == 2, "le fichier d'essai doit être stéréo"
        micro = niveaux_par_trame(donnees[:, 0], frequence)
        boucle = niveaux_par_trame(donnees[:, 1], frequence)
        assert max(boucle) < -45.0, "la fuite doit rester sous le plancher de bruit"
        assert not en_visio(micro, boucle)

    def test_le_micro_sert_de_reference_aux_deux_canaux(self, table: Path):
        """En présentiel, la boucle n'a rien à apporter : on ne s'en sert plus."""
        import numpy as np
        import soundfile as sf

        from greffier.adaptateurs.canaux_fichier import separer_canaux

        donnees, frequence = sf.read(table, dtype="float32", always_2d=True)
        canaux = separer_canaux(donnees, frequence)
        assert canaux.distante is False
        assert np.array_equal(canaux.systeme, canaux.micro)

    def test_aucun_passage_n_est_declare_local(self, table: Path):
        """Le canal ne désigne personne : mieux vaut rien que « Toi » à tort.

        Sur une visio, ces passages sont la seule attribution qui ne se trompe
        jamais. Autour d'une table, les retenir ferait de tous les participants
        une seule et même personne — mesuré : trois locuteurs ramenés à une
        étiquette « moi ».
        """
        from greffier.adaptateurs.canaux_fichier import LecteurCanauxFichier

        assert LecteurCanauxFichier().passages_locaux(table) == []


class TestChaineEnPresentiel:
    def test_la_reunion_est_transcrite(self, resultat):
        assert resultat.mots > 60, "la transcription a perdu l'essentiel du dialogue"

    def test_personne_n_est_etiquete_comme_la_voix_locale(self, resultat):
        """Le défaut que le présentiel pouvait faire apparaître, en toutes lettres."""
        assert VOIX_LOCALE not in resultat.temps_de_parole()

    def test_les_participants_ne_sont_pas_fondus_en_une_seule_voix(self, resultat):
        """Trois personnes autour d'une table restent plusieurs voix.

        Le compte exact dépend du timbre des voix de synthèse — deux d'entre
        elles se ressemblent assez pour être recollées — donc on vérifie qu'on
        n'a ni une seule voix, ni un participant par réplique.
        """
        significatives = resultat.voix_significatives()
        assert 2 <= len(significatives) <= len(resultat.repliques)

    def test_les_fragments_ne_comptent_pas_comme_des_participants(self, resultat):
        assert all(duree >= 10 for duree in resultat.voix_significatives().values())

    def test_l_auto_presentation_reste_juste_sans_le_secours_du_canal(self, resultat):
        """« moi c'est Jacques » désigne celui qui parle, canal ou pas."""
        assert resultat.nom_de(resultat.repliques[0].voix) == "Jacques"

    def test_aucune_phrase_a_cheval_n_est_attribuee(self, resultat):
        """Une phrase que deux voix se partagent ne doit désigner personne.

        C'est la règle de `domaine/attribution.py`, éprouvée ici sur la vraie
        chaîne : rien ne garantit que la découpe de whisper tombe sur un
        changement de locuteur, et le présentiel n'a pas le canal pour rattraper.
        """
        from greffier.domaine.attribution import PART_MINIMALE, temps_par_voix

        for replique in resultat.repliques:
            cumuls = temps_par_voix(replique.intervalle, resultat.tours)
            if not cumuls:
                continue
            part = max(cumuls.values()) / sum(cumuls.values())
            if part < PART_MINIMALE:
                assert replique.voix is None, (
                    f"« {replique.texte[:40]} » est partagée à {part:.0%} "
                    "et se voit pourtant attribuer une voix"
                )
