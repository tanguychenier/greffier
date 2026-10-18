"""The processor check on a macOS bundle, the guard the arm64-only 0.3.32 lacked."""

from __future__ import annotations

import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import check_bundle_architecture as check  # noqa: E402

X86_64 = 0x01000007
ARM64 = 0x0100000C


def thin(cpu_type: int, magic: bytes = check.THIN_64) -> bytes:
    return magic + struct.pack("<I", cpu_type) + b"\0" * 24


def fat(*cpu_types: int) -> bytes:
    slices = b"".join(struct.pack(">IIIII", cpu, 0, 0, 0, 0) for cpu in cpu_types)
    return check.FAT + struct.pack(">I", len(cpu_types)) + slices


def fat_64(*cpu_types: int) -> bytes:
    slices = b"".join(struct.pack(">IIQQII", cpu, 0, 0, 0, 0, 0) for cpu in cpu_types)
    return check.FAT_64 + struct.pack(">I", len(cpu_types)) + slices


class TestWhatAHeaderCarries:
    @pytest.mark.parametrize(("header", "expected"), [
        (thin(X86_64), {"x86_64"}),
        (thin(ARM64), {"arm64"}),
        (thin(ARM64, check.THIN_32), {"arm64"}),
        (fat(X86_64, ARM64), {"x86_64", "arm64"}),
        (fat(ARM64), {"arm64"}),
        (fat_64(X86_64, ARM64), {"x86_64", "arm64"}),
    ])
    def test_every_layout_names_its_processors(self, header, expected):
        assert check.architectures(header) == expected

    def test_an_unknown_processor_is_named_rather_than_dropped(self):
        assert check.architectures(thin(7, check.THIN_32)) == {"cpu-0x7"}

    @pytest.mark.parametrize("header", [thin(0xFFFFFFFF), fat(0xFFFFFFFF)])
    def test_a_processor_number_is_read_unsigned(self, header):
        assert check.architectures(header) == {"cpu-0xffffffff"}

    def test_eight_bytes_are_enough_for_a_thin_header(self):
        assert check.architectures(thin(X86_64)[:8]) == {"x86_64"}

    def test_a_fat_header_of_no_slice_is_not_a_binary(self):
        """Read as an empty set, it would lack every processor and fail the bundle."""
        assert check.architectures(fat()) is None

    @pytest.mark.parametrize("header", [
        b"",
        b"#!/bin/bash\necho\n",
        b"\x89PNG\r\n\x1a\n",
        check.THIN_64 + b"\0",
        check.FAT + b"\0",
    ])
    def test_what_is_not_a_whole_header_is_not_a_binary(self, header):
        assert check.architectures(header) is None

    def test_a_java_class_is_not_a_fat_binary(self):
        """Same four bytes; then minor 0, major 52, read as 52 slices."""
        assert check.architectures(check.FAT + struct.pack(">HH", 0, 52)) is None

    def test_a_count_announcing_more_slices_than_were_read_is_refused(self):
        assert check.architectures(fat(X86_64, ARM64)[:-1]) is None

    @pytest.mark.parametrize("count", [check.MOST_SLICES, check.MOST_SLICES + 1])
    def test_the_slice_ceiling_is_inclusive(self, count):
        header = fat(*[ARM64] * count)
        expected = {"arm64"} if count <= check.MOST_SLICES else None
        assert check.architectures(header + b"\0" * check.HEADER_SIZE) == expected

    def test_the_header_read_holds_the_largest_fat_table(self):
        assert len(fat_64(*[ARM64] * check.MOST_SLICES)) <= check.HEADER_SIZE


@pytest.fixture
def bundle(tmp_path):
    contents = tmp_path / "Greffier.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "lib").mkdir()
    (contents / "MacOS" / "Greffier").write_bytes(thin(ARM64))
    (contents / "lib" / "libpython3.13.dylib").write_bytes(fat(X86_64, ARM64))
    (contents / "Info.plist").write_text("<plist/>", encoding="utf-8")
    return tmp_path / "Greffier.app"


class TestTheBundle:
    def test_only_the_binaries_lacking_the_processor_are_named(self, bundle):
        found = list(check.strangers(bundle, "x86_64"))
        assert found == [(bundle / "Contents" / "MacOS" / "Greffier", {"arm64"})]

    def test_a_bundle_of_its_own_processor_has_no_stranger(self, bundle):
        assert list(check.strangers(bundle, "arm64")) == []

    def test_a_link_is_judged_through_its_target_only(self, bundle):
        link = bundle / "Contents" / "lib" / "lien.dylib"
        link.symlink_to(bundle / "Contents" / "MacOS" / "Greffier")
        names = [path.name for path, _ in check.strangers(bundle, "x86_64")]
        assert names == ["Greffier"]

    def test_the_command_fails_and_says_which_file(self, bundle, capsys):
        assert check.main([str(bundle), "--arch", "x86_64"]) == 1
        out = capsys.readouterr().out
        assert out == f"::error::{bundle / 'Contents/MacOS/Greffier'}: arm64, not x86_64\n"

    def test_every_processor_a_stranger_carries_is_listed(self, bundle, capsys):
        (bundle / "Contents" / "MacOS" / "Greffier").write_bytes(fat(7, ARM64))
        assert check.main([str(bundle), "--arch", "x86_64"]) == 1
        assert capsys.readouterr().out.endswith(": arm64, cpu-0x7, not x86_64\n")

    def test_the_processor_cannot_be_left_out(self, bundle, capsys):
        """Left out, every binary would be reported as « not None »."""
        with pytest.raises(SystemExit) as stopped:
            check.main([str(bundle)])
        assert stopped.value.code == 2
        assert "--arch" in capsys.readouterr().err

    def test_the_help_says_what_the_check_is_for(self, capsys):
        with pytest.raises(SystemExit):
            check.main(["--help"])
        words = " ".join(capsys.readouterr().out.split())
        assert "cannot run on the expected processor" in words

    def test_the_command_passes_and_says_so(self, bundle, capsys):
        assert check.main([str(bundle), "--arch", "arm64"]) == 0
        assert capsys.readouterr().out == "Every binary of Greffier.app runs on arm64.\n"

    def test_a_missing_bundle_is_a_failure_not_a_pass(self, tmp_path, capsys):
        assert check.main([str(tmp_path / "absent.app"), "--arch", "arm64"]) == 1
        assert "no such bundle" in capsys.readouterr().out

    def test_only_the_two_mac_processors_are_accepted(self, bundle):
        with pytest.raises(SystemExit):
            check.main([str(bundle), "--arch", "i386"])


@pytest.mark.skipif(platform.system() != "Darwin", reason="real Mach-O files are on macOS")
def test_a_real_system_binary_reads_as_lipo_reads_it():
    """/usr/bin/true is universal on every macOS that runs on both processors."""
    with Path("/usr/bin/true").open("rb") as stream:
        carried = check.architectures(stream.read(check.HEADER_SIZE))
    assert carried is not None
    assert platform.machine() in carried
    lipo = shutil.which("lipo")
    if lipo is None:
        pytest.skip("lipo needs the command line tools")
    answer = subprocess.run([lipo, "-archs", "/usr/bin/true"], capture_output=True,
                            text=True, check=True).stdout.split()
    assert carried == {"arm64" if a == "arm64e" else a for a in answer}
