"""The pure parts of the AppImage build: the icon out of the icns, the AppDir."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import build_appimage  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20


def icns(*blocks: tuple[bytes, bytes]) -> bytes:
    body = b"".join(kind + struct.pack(">I", len(data) + 8) + data for kind, data in blocks)
    return b"icns" + struct.pack(">I", len(body) + 8) + body


class TestTheIconOutOfTheMacOne:
    def test_the_256_pixel_png_is_taken(self, tmp_path):
        small, wanted = PNG + b"small", PNG + b"wanted"
        file = tmp_path / "Greffier.icns"
        file.write_bytes(icns((b"ic05", b"not a png"), (b"ic07", small), (b"ic08", wanted)))
        assert build_appimage.icon_from_icns(file) == wanted

    def test_failing_that_the_first_png_serves(self, tmp_path):
        file = tmp_path / "Greffier.icns"
        file.write_bytes(icns((b"ic07", PNG + b"only")))
        assert build_appimage.icon_from_icns(file) == PNG + b"only"

    def test_a_file_that_is_not_an_icns_is_refused(self, tmp_path):
        file = tmp_path / "x.icns"
        file.write_bytes(b"RIFF" + b"\0" * 20)
        with pytest.raises(ValueError, match="not an icns"):
            build_appimage.icon_from_icns(file)

    def test_the_repository_s_own_icon_holds_the_png(self):
        png = build_appimage.icon_from_icns(RACINE / "macos" / "Greffier.icns")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 10_000


class TestTheAppDir:
    def test_it_carries_what_an_appimage_needs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build_appimage, "DIST", tmp_path / "dist")
        monkeypatch.setattr(build_appimage, "APPDIR", tmp_path / "dist" / "Greffier.AppDir")
        bundled = tmp_path / "Greffier"
        bundled.mkdir()
        (bundled / "Greffier").write_bytes(b"#!/bin/sh\necho Greffier\n")
        appdir = build_appimage.lay_out(bundled)
        assert (appdir / "AppRun").stat().st_mode & 0o111, "AppRun runs"
        assert "Exec=Greffier" in (appdir / "greffier.desktop").read_text(encoding="utf-8")
        assert (appdir / "greffier.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert (appdir / ".DirIcon").exists()
        assert (appdir / "usr" / "bin" / "Greffier" / "Greffier").exists()
        assert "usr/bin/Greffier/Greffier" in (appdir / "AppRun").read_text(encoding="utf-8")
