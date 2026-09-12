"""How the CUDA libraries are shown to the system loader, and whether a card answers.

The `nvidia-*` wheels lay their libraries in the packages folder, outside the
path the loader looks in. Neither CTranslate2 nor onnxruntime finds them there,
and both fall back on the processor -- thirteen times slower on the
transcription, eight times on the speaker turns -- without saying a word. The
only other way to show them would be setting `LD_LIBRARY_PATH` before launching
Greffier, which no desktop shortcut does.
"""

from types import SimpleNamespace

import pytest

from greffier.adapters import cuda as adaptateur


@pytest.fixture
def wheels_in(monkeypatch, tmp_path):
    """An "nvidia" folder filled the way the wheels fill it."""
    for relatif in ("cublas/lib/libcublas.so.12", "cublas/lib/libcublasLt.so.12",
                    "cudnn/lib/libcudnn.so.9", "cudnn/lib/libcudnn_graph.so.9",
                    "cuda_nvrtc/lib/libnvrtc.so.12", "cuda_runtime/lib/libcudart.so.12",
                    "cufft/lib/libcufft.so.11", "curand/lib/libcurand.so.10"):
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
        names = [path.name for path in adaptateur.libraries()]
        assert set(names) == {"libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9",
                             "libcudnn_graph.so.9", "libnvrtc.so.12", "libcudart.so.12",
                             "libcufft.so.11", "libcurand.so.10"}

    def test_cublaslt_comes_before_cublas(self, wheels_in):
        """cuBLAS depends on it: loaded first, it would not find it."""
        names = [path.name for path in adaptateur.libraries()]
        assert names.index("libcublasLt.so.12") < names.index("libcublas.so.12")

    def test_without_the_wheels_there_is_nothing_to_load(self, monkeypatch):
        """Le cas ordinaire : elles ne servent qu'à une carte NVIDIA."""
        monkeypatch.setattr(adaptateur.importlib.util, "find_spec", lambda _name: None)
        assert adaptateur.libraries() == []

    def test_a_package_with_no_folder_does_not_make_it_fail(self, monkeypatch):
        monkeypatch.setattr(
            adaptateur.importlib.util, "find_spec",
            lambda _name: SimpleNamespace(submodule_search_locations=None),
        )
        assert adaptateur.libraries() == []


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
            adaptateur.show_to_the_loader()

        assert len(essais) == 8, "chaque bibliothèque doit avoir été tentée"


class TestUneCarteRepond:
    @pytest.fixture(autouse=True)
    def sans_memoire(self):
        """La réponse est mise en cache : chaque cas doit repartir de zéro."""
        adaptateur.a_card_answers.cache_clear()
        yield
        adaptateur.a_card_answers.cache_clear()

    def test_no_driver_means_no_card(self, monkeypatch):
        """Le cas de loin le plus courant : une machine sans NVIDIA."""
        def pas_de_pilote(_name, **_options):
            raise OSError("libcuda.so.1: cannot open shared object file")

        monkeypatch.setattr(adaptateur.ctypes, "CDLL", pas_de_pilote)
        assert adaptateur.a_card_answers() is False

    def test_a_driver_that_counts_one_card(self, monkeypatch):
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(1))
        assert adaptateur.a_card_answers() is True

    def test_a_driver_installed_without_a_card(self, monkeypatch):
        """Arrive dans un conteneur : le pilote est là, la carte n'est pas passée."""
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(0))
        assert adaptateur.a_card_answers() is False

    def test_a_driver_that_refuses_to_start(self, monkeypatch):
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(1, init=999))
        assert adaptateur.a_card_answers() is False

    def test_a_driver_that_cannot_count(self, monkeypatch):
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(1, count=999))
        assert adaptateur.a_card_answers() is False

    def test_a_driver_without_the_expected_calls(self, monkeypatch):
        """Une bibliothèque homonyme ne doit pas faire tomber le démarrage."""
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: object())
        assert adaptateur.a_card_answers() is False

    def test_the_driver_is_asked_only_once(self, monkeypatch):
        appels = []

        def compte(*_a, **_k):
            appels.append(1)
            return _Pilote(1)

        monkeypatch.setattr(adaptateur.ctypes, "CDLL", compte)
        adaptateur.a_card_answers()
        adaptateur.a_card_answers()
        assert len(appels) == 1


class _Pilote:
    """Ce que ctypes rend quand libcuda.so.1 est là."""

    def __init__(self, cartes: int, init: int = 0, count: int = 0) -> None:
        self._cartes = cartes
        self._init = init
        self._count = count

    def cuInit(self, _flags):  # noqa: N802 — c'est le nom dans la bibliothèque
        return self._init

    def cuDeviceGetCount(self, pointeur):  # noqa: N802 — idem
        pointeur._obj.value = self._cartes
        return self._count
