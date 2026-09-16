"""How the CUDA libraries are shown to the loader, and whether a card answers.

Checked for all three systems, since nobody has the three machines to hand: the
detected system is forced and what the adapter deduces from it is read back.

The `nvidia-*` wheels lay their libraries in the packages folder, outside the
path the loader looks in. Neither CTranslate2 nor onnxruntime finds them there,
and both fall back on the processor -- thirteen times slower on the
transcription, eight times on the speaker turns -- without saying a word. The
only other way to show them would be setting `LD_LIBRARY_PATH` before launching
Greffier, which no desktop shortcut does.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from greffier.adapters import cuda as adapter

ON_LINUX = ("cublas/lib/libcublas.so.12", "cublas/lib/libcublasLt.so.12",
              "cudnn/lib/libcudnn.so.9", "cudnn/lib/libcudnn_graph.so.9",
              "cuda_nvrtc/lib/libnvrtc.so.12", "cuda_runtime/lib/libcudart.so.12",
              "cufft/lib/libcufft.so.11", "curand/lib/libcurand.so.10")

ON_WINDOWS = ("cublas/bin/cublas64_12.dll", "cublas/bin/cublasLt64_12.dll",
                "cudnn/bin/cudnn64_9.dll", "cudnn/bin/cudnn_graph64_9.dll",
                "cuda_nvrtc/bin/nvrtc64_120_0.dll", "cuda_runtime/bin/cudart64_12.dll",
                "cufft/bin/cufft64_11.dll", "curand/bin/curand64_10.dll")


def _poser(monkeypatch, tmp_path, files):
    """An "nvidia" folder filled the way the wheels fill it."""
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(
        adapter.importlib.util, "find_spec",
        lambda _name: SimpleNamespace(submodule_search_locations=[str(tmp_path)]),
    )
    return tmp_path


@pytest.fixture
def wheels_in(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "SYSTEM", "Linux")
    return _poser(monkeypatch, tmp_path, ON_LINUX)


@pytest.fixture
def wheels_under_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "SYSTEM", "Windows")
    return _poser(monkeypatch, tmp_path, ON_WINDOWS)


class TestLibrariesFound:
    def test_every_library_is_returned(self, wheels_in):
        names = [path.name for path in adapter.libraries()]
        assert set(names) == {"libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9",
                             "libcudnn_graph.so.9", "libnvrtc.so.12", "libcudart.so.12",
                             "libcufft.so.11", "libcurand.so.10"}

    def test_cublaslt_comes_before_cublas(self, wheels_in):
        """cuBLAS depends on it: loaded first, it would not find it."""
        names = [path.name for path in adapter.libraries()]
        assert names.index("libcublasLt.so.12") < names.index("libcublas.so.12")

    def test_without_the_wheels_there_is_nothing_to_load(self, monkeypatch):
        """The ordinary case: they only serve an NVIDIA card."""
        monkeypatch.setattr(adapter.importlib.util, "find_spec", lambda _name: None)
        assert adapter.libraries() == []

    def test_a_package_with_no_folder_does_not_make_it_fail(self, monkeypatch):
        monkeypatch.setattr(
            adapter.importlib.util, "find_spec",
            lambda _name: SimpleNamespace(submodule_search_locations=None),
        )
        assert adapter.libraries() == []


class TestLoading:
    def test_an_unreadable_library_does_not_stop_the_transcription(self, wheels_in):
        """The card will be unusable, and falling back on the processor is enough:
        giving up transcribing for that would be worse than slow."""
        trials = []

        def loader_that_falls(path, **_options):
            trials.append(path)
            raise OSError("format non reconnu")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(adapter.ctypes, "CDLL", loader_that_falls)
            adapter.show_to_the_loader()

        assert len(trials) == 8, "chaque bibliothèque doit avoir été tentée"


class TestACardAnswers:
    @pytest.fixture(autouse=True)
    def without_memory(self):
        """The answer is cached: each case has to start from scratch."""
        adapter.a_card_answers.cache_clear()
        yield
        adapter.a_card_answers.cache_clear()

    def test_no_driver_means_no_card(self, monkeypatch):
        """By far the most common case: a machine without NVIDIA."""
        def no_driver(_name, **_options):
            raise OSError("libcuda.so.1: cannot open shared object file")

        monkeypatch.setattr(adapter.ctypes, "CDLL", no_driver)
        assert adapter.a_card_answers() is False

    def test_a_driver_that_counts_one_card(self, monkeypatch):
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *_a, **_k: _Driver(1))
        assert adapter.a_card_answers() is True

    def test_a_driver_installed_without_a_card(self, monkeypatch):
        """Happens in a container: the driver is there, the card was not passed through."""
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *_a, **_k: _Driver(0))
        assert adapter.a_card_answers() is False

    def test_a_driver_that_refuses_to_start(self, monkeypatch):
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *_a, **_k: _Driver(1, init=999))
        assert adapter.a_card_answers() is False

    def test_a_driver_that_cannot_count(self, monkeypatch):
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *_a, **_k: _Driver(1, count=999))
        assert adapter.a_card_answers() is False

    def test_a_driver_without_the_expected_calls(self, monkeypatch):
        """A library of the same name must not bring the start-up down."""
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *_a, **_k: object())
        assert adapter.a_card_answers() is False

    def test_the_driver_is_asked_only_once(self, monkeypatch):
        calls = []

        def account(*_a, **_k):
            calls.append(1)
            return _Driver(1)

        monkeypatch.setattr(adapter.ctypes, "CDLL", account)
        adapter.a_card_answers()
        adapter.a_card_answers()
        assert len(calls) == 1


class _Driver:
    """What ctypes returns when libcuda.so.1 is there."""

    def __init__(self, cards: int, init: int = 0, count: int = 0) -> None:
        self._cards = cards
        self._init = init
        self._count = count

    def cuInit(self, _flags):  # noqa: N802, it is the name in the library
        return self._init

    def cuDeviceGetCount(self, pointer):  # noqa: N802, idem
        pointer._obj.value = self._cards
        return self._count


class TestTwoOnnxEngines:
    """Two ONNX Runtimes do not fit in one process.

    faster-whisper brings its own with its voice detector. Measured: whichever
    opens second reads a corrupted graph (« node_index < nodes_.size() was
    false »), and when the versions are close enough to bind cleanly, the
    interpreter dies on a segmentation fault. Whichever opens first keeps the
    card; the other falls back on the processor.
    """

    @pytest.fixture(autouse=True)
    def without_memory(self, monkeypatch):
        """The seat kept and the driver's answer are remembered: start from scratch."""
        adapter.a_card_answers.cache_clear()
        monkeypatch.setattr(adapter, "_place_kept", False)

    @pytest.fixture
    def with_card(self, monkeypatch):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: True)

    @pytest.fixture
    def le_rival(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "onnxruntime", object())

    def test_the_rival_is_seen_when_it_is_loaded(self, le_rival):
        assert adapter.another_runtime_is_open() is True

    def test_no_rival_before_anything_transcribes(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        assert adapter.another_runtime_is_open() is False

    def test_the_card_is_lost_to_whoever_came_first(self, with_card, le_rival):
        assert adapter.a_card_is_usable() is False

    def test_keeping_the_place_holds_the_card(self, with_card, le_rival, monkeypatch):
        """The rival may load afterwards: the seat is taken."""
        monkeypatch.setattr(adapter, "_place_kept", True)
        assert adapter.a_card_is_usable() is True

    def test_without_a_card_nothing_is_usable(self, monkeypatch):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: False)
        assert adapter.a_card_is_usable() is False


class TestKeepingThePlace:
    @pytest.fixture(autouse=True)
    def without_memory(self, monkeypatch):
        """The seat kept and the driver's answer are remembered: start from scratch."""
        adapter.a_card_answers.cache_clear()
        monkeypatch.setattr(adapter, "_place_kept", False)

    @pytest.fixture
    def silent_sherpa(self, monkeypatch):
        """The model weighs a hundred megabytes: here the openings are counted."""
        openings = []
        monkeypatch.setitem(
            sys.modules, "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=lambda **o: o,
                SpeakerEmbeddingExtractor=lambda config: openings.append(config),
            ),
        )
        monkeypatch.setattr(adapter, "show_to_the_loader", lambda: None)
        return openings

    def test_the_place_is_kept_once(self, monkeypatch, tmp_path, silent_sherpa):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: True)
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        model = tmp_path / "empreintes.onnx"
        model.touch()
        adapter.keep_the_place(model)
        adapter.keep_the_place(model)
        assert len(silent_sherpa) == 1, "ouvrir deux fois coûterait une seconde pour rien"
        assert silent_sherpa[0]["provider"] == "cuda"

    def test_a_machine_without_a_card_keeps_nothing(self, monkeypatch, tmp_path, silent_sherpa):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: False)
        model = tmp_path / "empreintes.onnx"
        model.touch()
        adapter.keep_the_place(model)
        assert silent_sherpa == []

    def test_a_missing_model_keeps_nothing(self, monkeypatch, tmp_path, silent_sherpa):
        """Before the first installation of the models, there is nothing to open."""
        monkeypatch.setattr(adapter, "a_card_answers", lambda: True)
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        adapter.keep_the_place(tmp_path / "absent.onnx")
        assert silent_sherpa == []

    def test_a_model_that_refuses_does_not_stop_the_meeting(
        self, monkeypatch, tmp_path, silent_sherpa
    ):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: True)
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        monkeypatch.setitem(
            sys.modules, "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=lambda **o: o,
                SpeakerEmbeddingExtractor=_which_refuses,
            ),
        )
        model = tmp_path / "empreintes.onnx"
        model.touch()
        adapter.keep_the_place(model)


def _which_refuses(_config):
    raise RuntimeError("le modèle n'a pas pu être ouvert")


class TestTheThreeSystems:
    """Every system keeps its libraries elsewhere, or has none.

    The NVIDIA wheels put « .so » files under « lib/ » on Linux and « .dll »
    files under « bin/ » on Windows. macOS has had no NVIDIA card since Mojave:
    everything stays on the processor there, where whisper.cpp has Metal anyway.
    """

    def test_windows_looks_for_its_dll(self, wheels_under_windows):
        the_names = [path.name for path in adapter.libraries("Windows")]
        assert set(the_names) == {"cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll",
                             "cudnn_graph64_9.dll", "nvrtc64_120_0.dll",
                             "cudart64_12.dll", "cufft64_11.dll", "curand64_10.dll"}

    def test_windows_loads_cublaslt_before_cublas(self, wheels_under_windows):
        the_names = [path.name for path in adapter.libraries("Windows")]
        assert the_names.index("cublasLt64_12.dll") < the_names.index("cublas64_12.dll")

    def test_macos_has_nothing_to_load(self, wheels_in):
        """The files are there -- an untidy machine -- and still nothing."""
        assert adapter.libraries("Darwin") == []

    def test_macos_never_answers_for_a_card(self, monkeypatch):
        """And without even trying to open a driver that does not exist."""
        trials = []
        monkeypatch.setattr(adapter, "SYSTEM", "Darwin")
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *a, **k: trials.append(a))
        adapter.a_card_answers.cache_clear()
        assert adapter.a_card_answers() is False
        assert trials == []
        adapter.a_card_answers.cache_clear()

    @pytest.mark.parametrize(
        ("system", "the_driver"), [("Linux", "libcuda.so.1"), ("Windows", "nvcuda.dll")]
    )
    def test_each_system_asks_its_own_driver(self, monkeypatch, system, the_driver):
        requests: list[str] = []
        monkeypatch.setattr(adapter, "SYSTEM", system)
        monkeypatch.setattr(
            adapter.ctypes, "CDLL",
            lambda name, **_k: (requests.append(name), _Driver(1))[1],
        )
        adapter.a_card_answers.cache_clear()
        assert adapter.a_card_answers() is True
        assert requests == [the_driver]
        adapter.a_card_answers.cache_clear()

    def test_windows_declares_the_folder_to_the_loader(self, monkeypatch, wheels_under_windows):
        """Without it, a DLL loaded from here does not find those it depends on."""
        declares = []
        monkeypatch.setattr(adapter.os, "add_dll_directory", declares.append, raising=False)
        monkeypatch.setattr(adapter.ctypes, "CDLL", lambda *_a, **_k: None)
        adapter.show_to_the_loader()
        assert {Path(d).name for d in declares} == {"bin"}
        assert len(declares) == 6, "un dossier par paquet, pas un par fichier"


class TestTheComputationAnnounced:
    """What the diagnostic says of the computing available.

    « nvidia-smi is there » is not « a card answers »: a container may carry
    the tool without the card. The driver is the only safe source.
    """

    @pytest.fixture
    def diagnostic(self, monkeypatch):
        from greffier.adapters import system_diagnostic

        adapter.a_card_answers.cache_clear()
        monkeypatch.setattr(system_diagnostic, "SYSTEM", "Linux")
        return system_diagnostic

    def test_a_card_that_answers_is_announced(self, diagnostic, monkeypatch):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: True)
        assert diagnostic.speedup() == "cuda"

    def test_the_tool_without_the_card_is_not(self, diagnostic, monkeypatch):
        monkeypatch.setattr(adapter, "a_card_answers", lambda: False)
        assert diagnostic.speedup() == "processeur"

    def test_apple_silicon_has_metal_and_never_asks(self, monkeypatch):
        from greffier.adapters import system_diagnostic

        monkeypatch.setattr(system_diagnostic, "SYSTEM", "Darwin")
        monkeypatch.setattr(system_diagnostic.platform, "machine", lambda: "arm64")
        monkeypatch.setattr(adapter, "a_card_answers", _never_called)
        assert system_diagnostic.speedup() == "metal"


def _never_called():
    raise AssertionError("macOS n'a pas de carte NVIDIA à interroger")
