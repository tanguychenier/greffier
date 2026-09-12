"""Reading the levels in the file ffmpeg is currently writing.

The case that named it: the window showed "the others are speaking" when it was
whoever was recording. The header of a WAV produced by ffmpeg is 102 bytes and
not 44: an extended "fmt" of 40 bytes, then a "LIST" chunk of 26, and reading
from the wrong base shifted the reading by 29 samples, so by two channels out of
three.
"""

from __future__ import annotations

import struct
from pathlib import Path

from greffier.adapters.live_levels import lire_forme, read_level, written_duration
from greffier.domain.channels import WhoSpeaks


def wav(
    path: Path,
    channels: list[list[int]],
    frequency: int = 16000,
    avec_liste: bool = False,
    fmt_etendu: bool = False,
) -> Path:
    """Builds a WAV, with or without the chunks ffmpeg adds."""
    entrelace = bytearray()
    for trame in zip(*channels, strict=True):
        for value in trame:
            entrelace += struct.pack("<h", value)

    nb = len(channels)
    taille_fmt = 40 if fmt_etendu else 16
    fmt = struct.pack("<HHIIHH", 1, nb, frequency, frequency * nb * 2, nb * 2, 16)
    if fmt_etendu:
        fmt += b"\x00" * (taille_fmt - 16)
    chunks = b"fmt " + struct.pack("<I", taille_fmt) + fmt
    if avec_liste:
        info = b"INFOISFT" + struct.pack("<I", 14) + b"Lavf62.0.100\x00\x00"
        chunks += b"LIST" + struct.pack("<I", len(info)) + info
    # ffmpeg announces an unknown size while the file is still open.
    chunks += b"data" + struct.pack("<I", 0xFFFFFFFF) + bytes(entrelace)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks)
    return path


FORT = [12000] * 8000
MUET = [0] * 8000


class TestLectureDeLEntete:
    def test_a_canonical_header_is_read(self, tmp_path: Path) -> None:
        forme = lire_forme(wav(tmp_path / "a.wav", [FORT, MUET, MUET]))
        assert forme is not None
        assert forme.channels == 3 and forme.debut_donnees == 44

    def test_l_entete_reel_de_ffmpeg_est_lu(self, tmp_path: Path) -> None:
        # Extended "fmt" plus "LIST": 102 bytes, the shape seen in use.
        forme = lire_forme(
            wav(tmp_path / "b.wav", [FORT, MUET, MUET], avec_liste=True, fmt_etendu=True)
        )
        assert forme is not None
        assert forme.debut_donnees == 102

    def test_a_file_that_is_not_wav_is_refused(self, tmp_path: Path) -> None:
        faux = tmp_path / "c.wav"
        faux.write_bytes(b"pas du tout un wav" * 4)
        assert lire_forme(faux) is None

    def test_a_truncated_header_is_refused(self, tmp_path: Path) -> None:
        court = tmp_path / "d.wav"
        court.write_bytes(b"RIFF" + b"\x00" * 8)
        assert lire_forme(court) is None


class TestWhoIsSpeaking:
    def test_the_mic_alone_gives_you(self, tmp_path: Path) -> None:
        releve = read_level(wav(tmp_path / "a.wav", [FORT, MUET, MUET]))
        assert releve is not None
        assert releve.who is WhoSpeaks.YOU

    def test_the_channels_are_not_swapped_with_ffmpeg_s_header(
        self, tmp_path: Path
    ) -> None:
        # C'est le défaut constaté : avec ces chunks, la lecture était décalée
        # et l'interface annonçait « les autres parlent ».
        releve = read_level(
            wav(tmp_path / "b.wav", [FORT, MUET, MUET], avec_liste=True, fmt_etendu=True)
        )
        assert releve is not None
        assert releve.who is WhoSpeaks.YOU
        assert releve.mic_db > releve.system_db

    def test_the_loopback_alone_gives_the_others(self, tmp_path: Path) -> None:
        releve = read_level(
            wav(tmp_path / "c.wav", [MUET, FORT, FORT], avec_liste=True, fmt_etendu=True)
        )
        assert releve is not None
        assert releve.who is WhoSpeaks.THE_OTHERS

    def test_a_file_with_no_samples_returns_nothing(self, tmp_path: Path) -> None:
        assert read_level(wav(tmp_path / "d.wav", [[], [], []])) is None

    def test_a_missing_file_returns_nothing(self, tmp_path: Path) -> None:
        assert read_level(tmp_path / "jamais-ecrit.wav") is None


class TestTheLengthWrittenSoFar:
    """How much sound the file carries while ffmpeg is writing it.

    That length is what the live transcription follows. The meeting clock will not
    do: it takes the pauses out, while the file holds only what was captured.
    """

    def test_the_length_is_counted_in_bytes_not_in_the_header(self, tmp_path: Path) -> None:
        # L'en-tête annonce 0xFFFFFFFF tant que le fichier est ouvert : s'y fier
        # donnerait une durée absurde.
        file = wav(tmp_path / "en-cours.wav", [FORT, MUET], avec_liste=True,
                      fmt_etendu=True)
        assert written_duration(file) == 8000 / 16000

    def test_a_file_barely_opened_carries_nothing(self, tmp_path: Path) -> None:
        file = wav(tmp_path / "vide.wav", [[], []])
        assert written_duration(file) == 0.0

    def test_a_missing_file_gives_no_length(self, tmp_path: Path) -> None:
        # Le premier morceau n'existe pas encore quand la fenêtre lit l'état.
        assert written_duration(tmp_path / "rien.wav") is None
