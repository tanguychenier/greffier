"""How the CUDA libraries are shown to the system loader.

The `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` wheels lay their libraries in
the packages folder, outside the path the loader looks in. CTranslate2 does not
find them there and falls back on the processor, thirteen times slower, without
saying a word. The only other way to show them would be setting
`LD_LIBRARY_PATH` before launching Greffier, which no desktop shortcut does.
"""

from types import SimpleNamespace

import pytest

from greffier.adapters import transcription_faster_whisper as adaptateur


@pytest.fixture
def wheels_in(monkeypatch, tmp_path):
    """An "nvidia" folder filled the way the wheels fill it."""
    for relatif in ("cublas/lib/libcublas.so.12", "cublas/lib/libcublasLt.so.12",
                    "cudnn/lib/libcudnn.so.9", "cudnn/lib/libcudnn_graph.so.9",
                    "cuda_nvrtc/lib/libnvrtc.so.12"):
        path = tmp_path / relatif
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(
        adaptateur.importlib.util, "find_spec",
        lambda _name: SimpleNamespace(submodule_search_locations=[str(tmp_path)]),
    )
    return tmp_path


class TestBibliothequesTrouvees:
    def test_every_library_is_returned(self, wheels_in):
        names = [path.name for path in adaptateur.cuda_libraries()]
        assert set(names) == {"libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9",
                             "libcudnn_graph.so.9", "libnvrtc.so.12"}

    def test_cublaslt_comes_before_cublas(self, wheels_in):
        """cuBLAS depends on it: loaded first, it would not find it."""
        names = [path.name for path in adaptateur.cuda_libraries()]
        assert names.index("libcublasLt.so.12") < names.index("libcublas.so.12")

    def test_without_the_wheels_there_is_nothing_to_load(self, monkeypatch):
        """Le cas ordinaire : elles ne servent qu'à une carte NVIDIA."""
        monkeypatch.setattr(adaptateur.importlib.util, "find_spec", lambda _name: None)
        assert adaptateur.cuda_libraries() == []

    def test_a_package_with_no_folder_does_not_make_it_fail(self, monkeypatch):
        monkeypatch.setattr(
            adaptateur.importlib.util, "find_spec",
            lambda _name: SimpleNamespace(submodule_search_locations=None),
        )
        assert adaptateur.cuda_libraries() == []


class TestChargement:
    def test_an_unreadable_library_does_not_stop_the_transcription(self, wheels_in):
        """La carte sera inutilisable, et le repli sur le processeur suffit :
        renoncer à transcrire pour autant serait pire que lent."""
        essais = []

        def chargeur_qui_tombe(path, **_options):
            essais.append(path)
            raise OSError("format non reconnu")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(adaptateur.ctypes, "CDLL", chargeur_qui_tombe)
            adaptateur._show_cuda_to_the_loader()

        assert len(essais) == 5, "chaque bibliothèque doit avoir été tentée"
