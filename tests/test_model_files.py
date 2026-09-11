"""Les modèles que l'outil télécharge lui-même.

Le manque que ça répare : les modèles vivent hors de l'application — c'est
voulu, une mise à jour remplace le paquet et les 1,5 Go restent en place — donc
une application fraîchement téléchargée n'en a aucun. Seul l'installeur en
ligne de commande savait les chercher, si bien que double-cliquer sur l'archive
publiée donnait un outil incapable de transcrire quoi que ce soit.

Aucun téléchargement réel ici, sauf un test marqué `lent` : c'est
`urlopen` qui est remplacé, ce qui rend chaque cas éprouvable sans réseau.
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
        """On veut voir la barre bouger sur le gros fichier, pas l'attendre."""
        manquants = model_files.missing(tmp_path)
        assert manquants[0].name == "ggml-large-v3-turbo.bin"

    def test_a_model_already_there_is_not_asked_for(self, tmp_path):
        cible = tmp_path / "ggml-silero-v5.1.2.bin"
        cible.write_bytes(b"x" * 600_000)
        assert "ggml-silero-v5.1.2.bin" not in {m.name for m in model_files.missing(tmp_path)}

    def test_a_truncated_file_counts_as_missing(self, tmp_path):
        """Un téléchargement coupé laisse un fichier qui échoue bien plus tard."""
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
        """Sans lui, le direct se replie sur le grand modèle."""
        facultatifs = {m.name for m in model_files.CATALOGUE if not m.required}
        assert facultatifs == {"ggml-small.bin"}

    def test_the_voice_is_downloaded_everywhere(self):
        """C'est la partie qu'on entend : elle doit sonner pareil sur les trois
        systèmes. Le repli — le synthétiseur de chaque système — sonne
        différemment sur chacun, n'existe pas sur certaines sessions Linux, et
        fait machine là où il existe."""
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
        """Le point qui compte : un modèle à moitié échoue à la transcription."""
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
    """Un seul, et le plus petit : 0,9 Mo pour prouver que l'adresse répond.

    Les autres pèsent des centaines de mégaoctets ; les tirer à chaque essai
    coûterait plus que ce que ça prouve. Celui-ci vérifie ce qu'aucune doublure
    ne peut : que l'adresse publiée existe encore.
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
    """Le catalogue doit se lire sans le paquet installé.

    L'installeur tourne avant que pydantic n'existe : il charge ce module par
    son chemin, comme il charge déjà les emplacements et les langues. Deux
    copies de la liste auraient divergé au premier modèle changé.
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
