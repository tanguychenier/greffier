"""Ce que les canaux d'un enregistrement disent de la provenance du son.

Ces cas vivaient dans les tests des périphériques, et devaient forcer une
instance de diariseur sans l'initialiser pour atteindre une méthode privée. La
règle ayant son propre module, ils s'écrivent maintenant directement — et le
direct s'appuie sur le même code que le traitement final, ce qui est le point :
la fenêtre ne doit pas afficher un locuteur que le compte rendu contredira.
"""

from __future__ import annotations

import numpy as np

from greffier.adaptateurs.canaux_fichier import (
    LecteurCanauxFichier,
    niveaux_par_trame,
    separer_canaux,
)


def signal(canaux: list[list[float]]) -> np.ndarray:
    return np.array(canaux, dtype="float32").T


class TestVisioOuPresentiel:
    def test_une_boucle_qui_domine_signifie_visio(self) -> None:
        # Les autres passent par les haut-parleurs et couvrent le micro : c'est
        # ce qui distingue une visio, pas la simple présence d'un signal.
        fort, faible = [0.2] * 16000, [0.001] * 16000
        canaux = separer_canaux(signal([faible, fort, fort]))
        assert canaux.distante
        assert canaux.micro is not None

    def test_une_boucle_active_mais_jamais_dominante_reste_du_presentiel(self) -> None:
        # Le cas qui avait échoué : une boucle à -53 dB, du son y ayant fui,
        # mais qui ne couvre jamais le micro. Conclure « visio » attribuait
        # trente minutes de réunion à la seule personne qui enregistrait.
        canaux = separer_canaux(signal([[0.2] * 16000, [0.002] * 16000, [0.002] * 16000]))
        assert not canaux.distante
        # Et c'est le micro qu'il faut segmenter, là où tout le monde parle.
        assert float(abs(canaux.systeme).max()) > 0.1

    def test_une_boucle_muette_signifie_presentiel(self) -> None:
        # Le portable posé au milieu d'une table.
        canaux = separer_canaux(signal([[0.1] * 16000, [0.0] * 16000, [0.0] * 16000]))
        assert not canaux.distante
        assert float(abs(canaux.systeme).max()) > 0

    def test_un_canal_muet_ne_divise_pas_l_amplitude_des_autres(self) -> None:
        canaux = separer_canaux(signal([[0.001] * 16000, [0.0] * 16000, [0.2] * 16000]))
        assert canaux.distante
        assert float(abs(canaux.systeme).max()) > 0.15

    def test_un_fichier_mono_ne_permet_aucune_separation(self) -> None:
        canaux = separer_canaux(signal([[0.1] * 100]))
        assert canaux.micro is None and not canaux.distante


class TestUneVisioResteUneVisio:
    """Le verdict se lit sur l'ensemble de l'audio, pas sur dix secondes.

    Le défaut mesuré : sur une tranche où seule la personne au micro parle,
    aucune boucle ne domine, donc « présentiel » — et sa voix, cessant d'être
    désignée par le canal, devenait un participant distant de plus.
    """

    def test_le_mode_impose_l_emporte_sur_ce_que_dit_la_tranche(self) -> None:
        seule_ma_voix = signal([[0.2] * 16000, [0.0] * 16000, [0.0] * 16000])
        assert not separer_canaux(seule_ma_voix).distante
        assert separer_canaux(seule_ma_voix, distante=True).distante

    def test_une_boucle_muette_imposee_visio_laisse_la_parole_au_micro(self) -> None:
        # C'est ce qui permet de continuer à afficher « Toi » quand personne
        # d'autre ne parle pendant une tranche entière.
        canaux = separer_canaux(
            signal([[0.2] * 16000, [0.0] * 16000, [0.0] * 16000]), distante=True
        )
        assert canaux.micro is not None
        assert float(abs(canaux.systeme).max()) == 0.0

    def test_le_lecteur_retient_le_verdict_d_une_tranche_a_l_autre(
        self, tmp_path
    ) -> None:
        import soundfile as sf

        lecteur = LecteurCanauxFichier()
        assert not lecteur.distante
        # Une tranche de visio : la boucle couvre le micro.
        visio = tmp_path / "visio.wav"
        sf.write(visio, signal([[0.001] * 16000, [0.2] * 16000, [0.2] * 16000]), 16000)
        lecteur.passages_locaux(visio)
        assert lecteur.distante
        # La tranche suivante ne porte que ma voix : le verdict tient, et ce
        # passage m'est attribué au lieu de créer une voix distante.
        seul = tmp_path / "seul.wav"
        sf.write(seul, signal([[0.2] * 32000, [0.0] * 32000, [0.0] * 32000]), 16000)
        assert lecteur.passages_locaux(seul) != []


class TestNiveaux:
    def test_un_silence_numerique_ne_donne_pas_moins_l_infini(self) -> None:
        niveaux = niveaux_par_trame(np.zeros(16000, dtype="float32"), 16000)
        assert niveaux and all(n < -200 for n in niveaux)

    def test_un_signal_trop_court_pour_une_trame_ne_donne_rien(self) -> None:
        assert niveaux_par_trame(np.zeros(10, dtype="float32"), 16000) == []


class TestLecture:
    def test_un_fichier_illisible_n_interrompt_pas_la_reunion(self, tmp_path) -> None:
        # Une tranche découpée pendant l'écriture peut arriver tronquée : le
        # direct affiche alors la phrase sans « Toi », il ne s'arrête pas.
        absent = tmp_path / "rien.wav"
        assert LecteurCanauxFichier().passages_locaux(absent) == []
