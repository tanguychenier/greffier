"""The models the tool downloads by itself.

The gap this fills: the models live outside the application, deliberately, so
that an update replaces the bundle and the 1.5 GB stay in place. A freshly
downloaded application therefore has none of them. Only the command-line
installer knew how to fetch them, so double-clicking the published archive
gave a tool unable to transcribe anything at all.

No real download here, save one test marked `lent`: `urlopen` is what gets
replaced, which makes every case coverable with no network.
"""

from __future__ import annotations

import tarfile
import urllib.error
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from greffier.adapters import model_files


def answer_with(monkeypatch: pytest.MonkeyPatch, octets: bytes) -> None:
    class Reponse(BytesIO):
        headers = {"Content-Length": str(len(octets))}

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> bool:
            return False

    monkeypatch.setattr(
        model_files.urllib.request, "urlopen", lambda *_a, **_k: Reponse(octets)
    )


def fail_to_answer(monkeypatch: pytest.MonkeyPatch, souci: Exception) -> None:
    def tomber(*_a: Any, **_k: Any) -> Any:
        raise souci

    monkeypatch.setattr(model_files.urllib.request, "urlopen", tomber)


class TestWhatIsMissing:
    def test_a_fresh_installation_has_everything_to_fetch(self, tmp_path):
        manquants = model_files.missing(tmp_path)
        assert len(manquants) == len(model_files.CATALOGUE)

    def test_the_heaviest_comes_first(self, tmp_path):
        """One wants to see the bar move on the big file, not wait for it."""
        manquants = model_files.missing(tmp_path)
        assert manquants[0].name == "ggml-large-v3-turbo.bin"

    def test_a_model_already_there_is_not_asked_for(self, tmp_path):
        cible = tmp_path / "ggml-silero-v5.1.2.bin"
        cible.write_bytes(b"x" * 600_000)
        assert "ggml-silero-v5.1.2.bin" not in {m.name for m in model_files.missing(tmp_path)}

    def test_a_truncated_file_counts_as_missing(self, tmp_path):
        """A download cut short leaves a file that fails much later."""
        (tmp_path / "ggml-silero-v5.1.2.bin").write_bytes(b"x" * 12)
        assert "ggml-silero-v5.1.2.bin" in {m.name for m in model_files.missing(tmp_path)}

    def test_the_engine_decides_what_is_needed(self, tmp_path):
        """faster-whisper n'a pas besoin des fichiers de whisper.cpp."""
        noms = {m.name for m in model_files.missing(tmp_path, engine="faster-whisper")}
        assert "ggml-large-v3-turbo.bin" not in noms
        assert "diarisation/nemo_en_titanet_large.onnx" in noms

    def test_the_weight_is_said_in_words(self, tmp_path):
        assert model_files.weight(model_files.missing(tmp_path)).endswith("Go")
        petits = [m for m in model_files.CATALOGUE if m.minimum < 10_000_000]
        assert model_files.weight(petits).endswith("Mo")

    def test_only_the_live_model_is_optional(self):
        """Without it, the live thread falls back on the large model."""
        facultatifs = {m.name for m in model_files.CATALOGUE if not m.required}
        assert facultatifs == {"ggml-small.bin"}

    def test_the_voice_is_downloaded_everywhere(self):
        """It is the part that is heard: it has to sound the same on all three systems.
        The fallback, each system's own synthesiser, sounds different on each, does
        not exist on some Linux sessions, and sounds like a machine where it does.
        """
        voix = next(m for m in model_files.CATALOGUE if m.name == "voix")
        assert voix.required
        assert not voix.engine, "aucun système n'en est dispensé"


class TestDownloadingAModel:
    def _a_model(self) -> model_files.Model:
        return next(m for m in model_files.CATALOGUE if m.name.endswith("silero-v5.1.2.bin"))

    def test_the_model_is_written_and_the_progress_told(self, monkeypatch, tmp_path):
        octets = b"y" * 3_000_000
        answer_with(monkeypatch, octets)
        vus: list[tuple[int, int]] = []
        pose, where_in = model_files.fetch(
            self._a_model(), tmp_path, lambda r, t: vus.append((r, t))
        )
        assert pose, where_in
        assert (tmp_path / "ggml-silero-v5.1.2.bin").read_bytes() == octets
        assert vus and vus[-1][0] == len(octets)

    def test_nothing_truncated_is_left_if_the_network_drops(self, monkeypatch, tmp_path):
        """The point that counts: half a model fails at transcription time."""
        fail_to_answer(monkeypatch, urllib.error.URLError("coupé"))
        pose, souci = model_files.fetch(self._a_model(), tmp_path)
        assert not pose and souci == "pas de réseau"
        assert not list(tmp_path.iterdir()), "aucun fichier partiel ne doit rester"

    def test_a_subfolder_is_created_when_needed(self, monkeypatch, tmp_path):
        answer_with(monkeypatch, b"z" * 21_000_000)
        titanet = next(m for m in model_files.CATALOGUE if "titanet" in m.name)
        pose, _ = model_files.fetch(titanet, tmp_path)
        assert pose
        assert (tmp_path / "diarisation" / "nemo_en_titanet_large.onnx").exists()

    def test_an_archive_is_unpacked_under_the_expected_name(self, monkeypatch, tmp_path):
        """La voix arrive dans un dossier au nom du modèle : il faut le renommer."""
        boite = BytesIO()
        source = tmp_path / "vits-piper-fr_FR-upmc-medium"
        source.mkdir()
        (source / "model.onnx").write_bytes(b"poids")
        (source / "tokens.txt").write_text("a\n", encoding="utf-8")
        with tarfile.open(fileobj=boite, mode="w:bz2") as a:
            a.add(source, arcname="vits-piper-fr_FR-upmc-medium")
        answer_with(monkeypatch, boite.getvalue())

        cible = tmp_path / "modeles"
        voix = next(m for m in model_files.CATALOGUE if m.name == "voix")
        pose, where_in = model_files.fetch(voix, cible)
        assert pose, where_in
        assert (cible / "voix" / "model.onnx").exists()
        assert (cible / "voix" / "tokens.txt").exists()
        assert voix.present(cible)

    def test_an_unreadable_archive_is_refused(self, monkeypatch, tmp_path):
        answer_with(monkeypatch, b"ceci n'est pas une archive")
        voix = next(m for m in model_files.CATALOGUE if m.name == "voix")
        pose, _souci = model_files.fetch(voix, tmp_path)
        assert not pose
        assert not (tmp_path / "voix").exists()

    def test_nothing_lingers_after_a_failed_archive(self, monkeypatch, tmp_path):
        answer_with(monkeypatch, b"pas une archive")
        voix = next(m for m in model_files.CATALOGUE if m.name == "voix")
        model_files.fetch(voix, tmp_path)
        assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]


@pytest.mark.lent
class TestARealDownload:
    """One only, and the smallest: 0.9 MB to prove the address answers.

    The others weigh hundreds of megabytes; pulling them on every run would cost
    more than it proves. This one checks what no double can: that the published
    address still exists.
    """

    def test_the_speech_detector_really_downloads(self, tmp_path):
        silero = next(
            m for m in model_files.CATALOGUE if m.name.endswith("silero-v5.1.2.bin")
        )
        pose, where_in = model_files.fetch(silero, tmp_path, delai=180.0)
        if not pose and where_in == "pas de réseau":
            pytest.skip("pas de réseau")
        assert pose, where_in
        assert silero.present(tmp_path)
        assert Path(where_in).stat().st_size >= silero.minimum


class TestOneCatalogueOnly:
    """The catalogue has to be readable without the package installed.

    The installer runs before pydantic exists: it loads this module by its path,
    as it already loads the locations and the languages. Two copies of the list
    would have drifted apart on the first model changed.
    """

    def test_it_loads_by_its_path_alone(self):
        import importlib.util
        import sys

        nom = "greffier_catalogue_essai"
        path = Path("src/greffier/adapters/model_files.py")
        specification = importlib.util.spec_from_file_location(nom, path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[nom] = module
        try:
            specification.loader.exec_module(module)
            assert len(module.CATALOGUE) == len(model_files.CATALOGUE)
        finally:
            del sys.modules[nom]

    def test_it_imports_nothing_from_the_project(self):
        """Sinon il ne pourrait pas se charger seul."""
        source = Path("src/greffier/adapters/model_files.py").read_text(encoding="utf-8")
        assert "import greffier" not in source
        assert "from greffier" not in source

    def test_the_installer_reads_this_catalogue(self):
        source = Path("tools/install.py").read_text(encoding="utf-8")
        assert "adapters/model_files.py" in source
