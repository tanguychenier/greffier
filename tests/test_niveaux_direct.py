"""Lecture des niveaux dans le fichier que ffmpeg est en train d'écrire.

Le cas nommé : l'interface affichait « les autres parlent » quand c'était la
personne qui enregistrait. L'en-tête d'un WAV produit par ffmpeg fait 102 octets
et non 44 — un « fmt » étendu de 40 octets, puis un chunk « LIST » de 26 — et
lire à la mauvaise base décalait la lecture de 29 échantillons, donc de deux
canaux sur trois.
"""

from __future__ import annotations

import struct
from pathlib import Path

from greffier.adaptateurs.niveaux_direct import duree_ecrite, lire_forme, relever
from greffier.domaine.canaux import QuiParle


def wav(
    chemin: Path,
    canaux: list[list[int]],
    frequence: int = 16000,
    avec_liste: bool = False,
    fmt_etendu: bool = False,
) -> Path:
    """Fabrique un WAV, avec ou sans les chunks que ffmpeg ajoute."""
    entrelace = bytearray()
    for trame in zip(*canaux, strict=True):
        for valeur in trame:
            entrelace += struct.pack("<h", valeur)

    nb = len(canaux)
    taille_fmt = 40 if fmt_etendu else 16
    fmt = struct.pack("<HHIIHH", 1, nb, frequence, frequence * nb * 2, nb * 2, 16)
    if fmt_etendu:
        fmt += b"\x00" * (taille_fmt - 16)
    morceaux = b"fmt " + struct.pack("<I", taille_fmt) + fmt
    if avec_liste:
        info = b"INFOISFT" + struct.pack("<I", 14) + b"Lavf62.0.100\x00\x00"
        morceaux += b"LIST" + struct.pack("<I", len(info)) + info
    # ffmpeg annonce une taille indéterminée tant que le fichier est ouvert.
    morceaux += b"data" + struct.pack("<I", 0xFFFFFFFF) + bytes(entrelace)
    chemin.write_bytes(b"RIFF" + struct.pack("<I", len(morceaux) + 4) + b"WAVE" + morceaux)
    return chemin


FORT = [12000] * 8000
MUET = [0] * 8000


class TestLectureDeLEntete:
    def test_un_entete_canonique_est_lu(self, tmp_path: Path) -> None:
        forme = lire_forme(wav(tmp_path / "a.wav", [FORT, MUET, MUET]))
        assert forme is not None
        assert forme.canaux == 3 and forme.debut_donnees == 44

    def test_l_entete_reel_de_ffmpeg_est_lu(self, tmp_path: Path) -> None:
        # « fmt » étendu plus « LIST » : 102 octets, la forme observée en usage.
        forme = lire_forme(
            wav(tmp_path / "b.wav", [FORT, MUET, MUET], avec_liste=True, fmt_etendu=True)
        )
        assert forme is not None
        assert forme.debut_donnees == 102

    def test_un_fichier_qui_n_est_pas_du_wav_est_refuse(self, tmp_path: Path) -> None:
        faux = tmp_path / "c.wav"
        faux.write_bytes(b"pas du tout un wav" * 4)
        assert lire_forme(faux) is None

    def test_un_entete_tronque_est_refuse(self, tmp_path: Path) -> None:
        court = tmp_path / "d.wav"
        court.write_bytes(b"RIFF" + b"\x00" * 8)
        assert lire_forme(court) is None


class TestQuiParle:
    def test_le_micro_seul_actif_donne_toi(self, tmp_path: Path) -> None:
        releve = relever(wav(tmp_path / "a.wav", [FORT, MUET, MUET]))
        assert releve is not None
        assert releve.qui is QuiParle.TOI

    def test_les_canaux_ne_sont_pas_inverses_avec_l_entete_de_ffmpeg(
        self, tmp_path: Path
    ) -> None:
        # C'est le défaut constaté : avec ces chunks, la lecture était décalée
        # et l'interface annonçait « les autres parlent ».
        releve = relever(
            wav(tmp_path / "b.wav", [FORT, MUET, MUET], avec_liste=True, fmt_etendu=True)
        )
        assert releve is not None
        assert releve.qui is QuiParle.TOI
        assert releve.micro_db > releve.systeme_db

    def test_la_boucle_seule_active_donne_les_autres(self, tmp_path: Path) -> None:
        releve = relever(
            wav(tmp_path / "c.wav", [MUET, FORT, FORT], avec_liste=True, fmt_etendu=True)
        )
        assert releve is not None
        assert releve.qui is QuiParle.LES_AUTRES

    def test_un_fichier_sans_echantillons_ne_rend_rien(self, tmp_path: Path) -> None:
        assert relever(wav(tmp_path / "d.wav", [[], [], []])) is None

    def test_un_fichier_absent_ne_rend_rien(self, tmp_path: Path) -> None:
        assert relever(tmp_path / "jamais-ecrit.wav") is None


class TestDureeEcrite:
    """Combien de son le fichier porte, pendant que ffmpeg l'écrit.

    C'est cette durée que suit la transcription en direct. L'horloge de la
    réunion ne convient pas : elle retire les pauses, alors que le fichier ne
    contient que ce qui a été capté.
    """

    def test_la_duree_se_compte_en_octets_et_non_dans_l_entete(self, tmp_path: Path) -> None:
        # L'en-tête annonce 0xFFFFFFFF tant que le fichier est ouvert : s'y fier
        # donnerait une durée absurde.
        fichier = wav(tmp_path / "en-cours.wav", [FORT, MUET], avec_liste=True,
                      fmt_etendu=True)
        assert duree_ecrite(fichier) == 8000 / 16000

    def test_un_fichier_a_peine_ouvert_ne_porte_rien(self, tmp_path: Path) -> None:
        fichier = wav(tmp_path / "vide.wav", [[], []])
        assert duree_ecrite(fichier) == 0.0

    def test_un_fichier_absent_ne_donne_pas_de_duree(self, tmp_path: Path) -> None:
        # Le premier morceau n'existe pas encore quand la fenêtre lit l'état.
        assert duree_ecrite(tmp_path / "rien.wav") is None
