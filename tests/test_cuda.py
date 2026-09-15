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

from greffier.adapters import cuda as adaptateur

SOUS_LINUX = ("cublas/lib/libcublas.so.12", "cublas/lib/libcublasLt.so.12",
              "cudnn/lib/libcudnn.so.9", "cudnn/lib/libcudnn_graph.so.9",
              "cuda_nvrtc/lib/libnvrtc.so.12", "cuda_runtime/lib/libcudart.so.12",
              "cufft/lib/libcufft.so.11", "curand/lib/libcurand.so.10")

SOUS_WINDOWS = ("cublas/bin/cublas64_12.dll", "cublas/bin/cublasLt64_12.dll",
                "cudnn/bin/cudnn64_9.dll", "cudnn/bin/cudnn_graph64_9.dll",
                "cuda_nvrtc/bin/nvrtc64_120_0.dll", "cuda_runtime/bin/cudart64_12.dll",
                "cufft/bin/cufft64_11.dll", "curand/bin/curand64_10.dll")


def _poser(monkeypatch, tmp_path, fichiers):
    """An "nvidia" folder filled the way the wheels fill it."""
    for relatif in fichiers:
        path = tmp_path / relatif
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(
        adaptateur.importlib.util, "find_spec",
        lambda _name: SimpleNamespace(submodule_search_locations=[str(tmp_path)]),
    )
    return tmp_path


@pytest.fixture
def wheels_in(monkeypatch, tmp_path):
    monkeypatch.setattr(adaptateur, "SYSTEM", "Linux")
    return _poser(monkeypatch, tmp_path, SOUS_LINUX)


@pytest.fixture
def wheels_under_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(adaptateur, "SYSTEM", "Windows")
    return _poser(monkeypatch, tmp_path, SOUS_WINDOWS)


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
        """The ordinary case: they only serve an NVIDIA card."""
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
        """The card will be unusable, and falling back on the processor is enough:
        giving up transcribing for that would be worse than slow."""
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
        """The answer is cached: each case has to start from scratch."""
        adaptateur.a_card_answers.cache_clear()
        yield
        adaptateur.a_card_answers.cache_clear()

    def test_no_driver_means_no_card(self, monkeypatch):
        """By far the most common case: a machine without NVIDIA."""
        def pas_de_pilote(_name, **_options):
            raise OSError("libcuda.so.1: cannot open shared object file")

        monkeypatch.setattr(adaptateur.ctypes, "CDLL", pas_de_pilote)
        assert adaptateur.a_card_answers() is False

    def test_a_driver_that_counts_one_card(self, monkeypatch):
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(1))
        assert adaptateur.a_card_answers() is True

    def test_a_driver_installed_without_a_card(self, monkeypatch):
        """Happens in a container: the driver is there, the card was not passed through."""
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(0))
        assert adaptateur.a_card_answers() is False

    def test_a_driver_that_refuses_to_start(self, monkeypatch):
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(1, init=999))
        assert adaptateur.a_card_answers() is False

    def test_a_driver_that_cannot_count(self, monkeypatch):
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: _Pilote(1, count=999))
        assert adaptateur.a_card_answers() is False

    def test_a_driver_without_the_expected_calls(self, monkeypatch):
        """A library of the same name must not bring the start-up down."""
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
    """What ctypes returns when libcuda.so.1 is there."""

    def __init__(self, cartes: int, init: int = 0, count: int = 0) -> None:
        self._cartes = cartes
        self._init = init
        self._count = count

    def cuInit(self, _flags):  # noqa: N802, it is the name in the library
        return self._init

    def cuDeviceGetCount(self, pointeur):  # noqa: N802, idem
        pointeur._obj.value = self._cartes
        return self._count


class TestDeuxMoteursOnnx:
    """Two ONNX Runtimes do not fit in one process.

    faster-whisper brings its own with its voice detector. Measured: whichever
    opens second reads a corrupted graph (« node_index < nodes_.size() was
    false »), and when the versions are close enough to bind cleanly, the
    interpreter dies on a segmentation fault. Whichever opens first keeps the
    card; the other falls back on the processor.
    """

    @pytest.fixture(autouse=True)
    def sans_memoire(self, monkeypatch):
        """The seat kept and the driver's answer are remembered: start from scratch."""
        adaptateur.a_card_answers.cache_clear()
        monkeypatch.setattr(adaptateur, "_place_kept", False)

    @pytest.fixture
    def avec_carte(self, monkeypatch):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: True)

    @pytest.fixture
    def le_rival(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "onnxruntime", object())

    def test_the_rival_is_seen_when_it_is_loaded(self, le_rival):
        assert adaptateur.another_runtime_is_open() is True

    def test_no_rival_before_anything_transcribes(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        assert adaptateur.another_runtime_is_open() is False

    def test_the_card_is_lost_to_whoever_came_first(self, avec_carte, le_rival):
        assert adaptateur.a_card_is_usable() is False

    def test_keeping_the_place_holds_the_card(self, avec_carte, le_rival, monkeypatch):
        """The rival may load afterwards: the seat is taken."""
        monkeypatch.setattr(adaptateur, "_place_kept", True)
        assert adaptateur.a_card_is_usable() is True

    def test_without_a_card_nothing_is_usable(self, monkeypatch):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: False)
        assert adaptateur.a_card_is_usable() is False


class TestGarderLaPlace:
    @pytest.fixture(autouse=True)
    def sans_memoire(self, monkeypatch):
        """The seat kept and the driver's answer are remembered: start from scratch."""
        adaptateur.a_card_answers.cache_clear()
        monkeypatch.setattr(adaptateur, "_place_kept", False)

    @pytest.fixture
    def sherpa_muet(self, monkeypatch):
        """The model weighs a hundred megabytes: here the openings are counted."""
        ouvertures = []
        monkeypatch.setitem(
            sys.modules, "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=lambda **o: o,
                SpeakerEmbeddingExtractor=lambda config: ouvertures.append(config),
            ),
        )
        monkeypatch.setattr(adaptateur, "show_to_the_loader", lambda: None)
        return ouvertures

    def test_the_place_is_kept_once(self, monkeypatch, tmp_path, sherpa_muet):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: True)
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        modele = tmp_path / "empreintes.onnx"
        modele.touch()
        adaptateur.keep_the_place(modele)
        adaptateur.keep_the_place(modele)
        assert len(sherpa_muet) == 1, "ouvrir deux fois coûterait une seconde pour rien"
        assert sherpa_muet[0]["provider"] == "cuda"

    def test_a_machine_without_a_card_keeps_nothing(self, monkeypatch, tmp_path, sherpa_muet):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: False)
        modele = tmp_path / "empreintes.onnx"
        modele.touch()
        adaptateur.keep_the_place(modele)
        assert sherpa_muet == []

    def test_a_missing_model_keeps_nothing(self, monkeypatch, tmp_path, sherpa_muet):
        """Before the first installation of the models, there is nothing to open."""
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: True)
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        adaptateur.keep_the_place(tmp_path / "absent.onnx")
        assert sherpa_muet == []

    def test_a_model_that_refuses_does_not_stop_the_meeting(
        self, monkeypatch, tmp_path, sherpa_muet
    ):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: True)
        monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
        monkeypatch.setitem(
            sys.modules, "sherpa_onnx",
            SimpleNamespace(
                SpeakerEmbeddingExtractorConfig=lambda **o: o,
                SpeakerEmbeddingExtractor=_qui_refuse,
            ),
        )
        modele = tmp_path / "empreintes.onnx"
        modele.touch()
        adaptateur.keep_the_place(modele)


def _qui_refuse(_config):
    raise RuntimeError("le modèle n'a pas pu être ouvert")


class TestLesTroisSystemes:
    """Every system keeps its libraries elsewhere, or has none.

    The NVIDIA wheels put « .so » files under « lib/ » on Linux and « .dll »
    files under « bin/ » on Windows. macOS has had no NVIDIA card since Mojave:
    everything stays on the processor there, where whisper.cpp has Metal anyway.
    """

    def test_windows_looks_for_its_dll(self, wheels_under_windows):
        noms = [chemin.name for chemin in adaptateur.libraries("Windows")]
        assert set(noms) == {"cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll",
                             "cudnn_graph64_9.dll", "nvrtc64_120_0.dll",
                             "cudart64_12.dll", "cufft64_11.dll", "curand64_10.dll"}

    def test_windows_loads_cublaslt_before_cublas(self, wheels_under_windows):
        noms = [chemin.name for chemin in adaptateur.libraries("Windows")]
        assert noms.index("cublasLt64_12.dll") < noms.index("cublas64_12.dll")

    def test_macos_has_nothing_to_load(self, wheels_in):
        """The files are there -- an untidy machine -- and still nothing."""
        assert adaptateur.libraries("Darwin") == []

    def test_macos_never_answers_for_a_card(self, monkeypatch):
        """And without even trying to open a driver that does not exist."""
        essais = []
        monkeypatch.setattr(adaptateur, "SYSTEM", "Darwin")
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *a, **k: essais.append(a))
        adaptateur.a_card_answers.cache_clear()
        assert adaptateur.a_card_answers() is False
        assert essais == []
        adaptateur.a_card_answers.cache_clear()

    @pytest.mark.parametrize(
        ("system", "pilote"), [("Linux", "libcuda.so.1"), ("Windows", "nvcuda.dll")]
    )
    def test_each_system_asks_its_own_driver(self, monkeypatch, system, pilote):
        demandes: list[str] = []
        monkeypatch.setattr(adaptateur, "SYSTEM", system)
        monkeypatch.setattr(
            adaptateur.ctypes, "CDLL",
            lambda nom, **_k: (demandes.append(nom), _Pilote(1))[1],
        )
        adaptateur.a_card_answers.cache_clear()
        assert adaptateur.a_card_answers() is True
        assert demandes == [pilote]
        adaptateur.a_card_answers.cache_clear()

    def test_windows_declares_the_folder_to_the_loader(self, monkeypatch, wheels_under_windows):
        """Without it, a DLL loaded from here does not find those it depends on."""
        declares = []
        monkeypatch.setattr(adaptateur.os, "add_dll_directory", declares.append, raising=False)
        monkeypatch.setattr(adaptateur.ctypes, "CDLL", lambda *_a, **_k: None)
        adaptateur.show_to_the_loader()
        assert {Path(d).name for d in declares} == {"bin"}
        assert len(declares) == 6, "un dossier par paquet, pas un par fichier"


class TestLeCalculAnnonce:
    """What the diagnostic says of the computing available.

    « nvidia-smi is there » is not « a card answers »: a container may carry
    the tool without the card. The driver is the only safe source.
    """

    @pytest.fixture
    def diagnostic(self, monkeypatch):
        from greffier.adapters import system_diagnostic

        adaptateur.a_card_answers.cache_clear()
        monkeypatch.setattr(system_diagnostic, "SYSTEM", "Linux")
        return system_diagnostic

    def test_a_card_that_answers_is_announced(self, diagnostic, monkeypatch):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: True)
        assert diagnostic.speedup() == "cuda"

    def test_the_tool_without_the_card_is_not(self, diagnostic, monkeypatch):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: False)
        assert diagnostic.speedup() == "processeur"

    def test_apple_silicon_has_metal_and_never_asks(self, monkeypatch):
        from greffier.adapters import system_diagnostic

        monkeypatch.setattr(system_diagnostic, "SYSTEM", "Darwin")
        monkeypatch.setattr(system_diagnostic.platform, "machine", lambda: "arm64")
        monkeypatch.setattr(adaptateur, "a_card_answers", _jamais_appele)
        assert system_diagnostic.speedup() == "metal"


def _jamais_appele():
    raise AssertionError("macOS n'a pas de carte NVIDIA à interroger")
