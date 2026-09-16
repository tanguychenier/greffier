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

from greffier.adapters.live_levels import read_level, read_shape, written_duration
from greffier.domain.channels import WhoSpeaks


def wav(
    path: Path,
    channels: list[list[int]],
    frequency: int = 16000,
    with_list: bool = False,
    extended_fmt: bool = False,
) -> Path:
    """Builds a WAV, with or without the chunks ffmpeg adds."""
    interleaved = bytearray()
    for frame in zip(*channels, strict=True):
        for value in frame:
            interleaved += struct.pack("<h", value)

    nb = len(channels)
    size_fmt = 40 if extended_fmt else 16
    fmt = struct.pack("<HHIIHH", 1, nb, frequency, frequency * nb * 2, nb * 2, 16)
    if extended_fmt:
        fmt += b"\x00" * (size_fmt - 16)
    chunks = b"fmt " + struct.pack("<I", size_fmt) + fmt
    if with_list:
        info = b"INFOISFT" + struct.pack("<I", 14) + b"Lavf62.0.100\x00\x00"
        chunks += b"LIST" + struct.pack("<I", len(info)) + info
    # ffmpeg announces an unknown size while the file is still open.
    chunks += b"data" + struct.pack("<I", 0xFFFFFFFF) + bytes(interleaved)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks)
    return path


FORT = [12000] * 8000
SILENT = [0] * 8000


class TestReadingTheHeader:
    def test_a_canonical_header_is_read(self, tmp_path: Path) -> None:
        shape = read_shape(wav(tmp_path / "a.wav", [FORT, SILENT, SILENT]))
        assert shape is not None
        assert shape.channels == 3 and shape.data_start == 44

    def test_l_entete_reel_de_ffmpeg_est_lu(self, tmp_path: Path) -> None:
        # Extended "fmt" plus "LIST": 102 bytes, the shape seen in use.
        shape = read_shape(
            wav(tmp_path / "b.wav", [FORT, SILENT, SILENT], with_list=True, extended_fmt=True)
        )
        assert shape is not None
        assert shape.data_start == 102

    def test_a_file_that_is_not_wav_is_refused(self, tmp_path: Path) -> None:
        wrong = tmp_path / "c.wav"
        wrong.write_bytes(b"pas du tout un wav" * 4)
        assert read_shape(wrong) is None

    def test_a_truncated_header_is_refused(self, tmp_path: Path) -> None:
        court = tmp_path / "d.wav"
        court.write_bytes(b"RIFF" + b"\x00" * 8)
        assert read_shape(court) is None


class TestWhoIsSpeaking:
    def test_the_mic_alone_gives_you(self, tmp_path: Path) -> None:
        reading_ = read_level(wav(tmp_path / "a.wav", [FORT, SILENT, SILENT]))
        assert reading_ is not None
        assert reading_.who is WhoSpeaks.YOU

    def test_the_channels_are_not_swapped_with_ffmpeg_s_header(
        self, tmp_path: Path
    ) -> None:
        # The defect seen: with these chunks, the reading was offset
        # et l'interface annonçait « les autres parlent ».
        reading_ = read_level(
            wav(tmp_path / "b.wav", [FORT, SILENT, SILENT], with_list=True, extended_fmt=True)
        )
        assert reading_ is not None
        assert reading_.who is WhoSpeaks.YOU
        assert reading_.mic_db > reading_.system_db

    def test_the_loopback_alone_gives_the_others(self, tmp_path: Path) -> None:
        reading_ = read_level(
            wav(tmp_path / "c.wav", [SILENT, FORT, FORT], with_list=True, extended_fmt=True)
        )
        assert reading_ is not None
        assert reading_.who is WhoSpeaks.THE_OTHERS

    def test_a_file_with_no_samples_returns_nothing(self, tmp_path: Path) -> None:
        assert read_level(wav(tmp_path / "d.wav", [[], [], []])) is None

    def test_a_missing_file_returns_nothing(self, tmp_path: Path) -> None:
        assert read_level(tmp_path / "jamais-ecrit.wav") is None


class TestTheLevelAtAGivenMoment:
    """A recording replayed from a finished file has its "now" in the middle."""

    def test_the_window_ends_where_it_is_asked_to(self, tmp_path: Path) -> None:
        # Half a second loud, half a second silent, at 16 kHz.
        loud_then_quiet = [12000] * 8000 + [0] * 8000
        audio = wav(tmp_path / "d.wav", [loud_then_quiet])
        assert read_level(audio, window_s=0.25, up_to=0.5).who is WhoSpeaks.YOU
        assert read_level(audio, window_s=0.25, up_to=1.0).who is WhoSpeaks.NOBODY

    def test_beyond_the_end_it_reads_the_end(self, tmp_path: Path) -> None:
        audio = wav(tmp_path / "e.wav", [[12000] * 8000])
        assert read_level(audio, window_s=0.25, up_to=9.0).who is WhoSpeaks.YOU

    def test_before_the_first_sample_there_is_nothing(self, tmp_path: Path) -> None:
        audio = wav(tmp_path / "f.wav", [[12000] * 8000])
        assert read_level(audio, window_s=0.25, up_to=0.0) is None


class TestTheLengthWrittenSoFar:
    """How much sound the file carries while ffmpeg is writing it.

    That length is what the live transcription follows. The meeting clock will not
    do: it takes the pauses out, while the file holds only what was captured.
    """

    def test_the_length_is_counted_in_bytes_not_in_the_header(self, tmp_path: Path) -> None:
        # The header announces 0xFFFFFFFF as long as the file is open: trusting it
        # donnerait une durée absurde.
        file = wav(tmp_path / "en-cours.wav", [FORT, SILENT], with_list=True,
                      extended_fmt=True)
        assert written_duration(file) == 8000 / 16000

    def test_a_file_barely_opened_carries_nothing(self, tmp_path: Path) -> None:
        file = wav(tmp_path / "vide.wav", [[], []])
        assert written_duration(file) == 0.0

    def test_a_missing_file_gives_no_length(self, tmp_path: Path) -> None:
        # The first chunk does not exist yet when the window reads the state.
        assert written_duration(tmp_path / "rien.wav") is None
