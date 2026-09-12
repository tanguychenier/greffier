"""How the CUDA libraries are shown to the system loader, and whether a card answers.

The `nvidia-*` wheels lay their libraries in the packages folder, outside the
path the loader looks in. Neither CTranslate2 nor onnxruntime finds them there,
and both fall back on the processor -- thirteen times slower on the
transcription, eight times on the speaker turns -- without saying a word. The
only other way to show them would be setting `LD_LIBRARY_PATH` before launching
Greffier, which no desktop shortcut does.
"""

import sys
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


class TestDeuxMoteursOnnx:
    """Deux ONNX Runtime ne tiennent pas dans un processus.

    faster-whisper amène le sien avec son détecteur de voix. Mesuré : celui qui
    ouvre en second lit un graphe corrompu (« node_index < nodes_.size() was
    false »), et quand les versions sont assez proches pour se lier proprement,
    l'interpréteur meurt sur une erreur de segmentation. Celui qui ouvre le
    premier garde la carte ; l'autre se replie sur le processeur.
    """

    @pytest.fixture(autouse=True)
    def sans_memoire(self, monkeypatch):
        """La place gardée et la réponse du pilote sont retenues : on repart de zéro."""
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
        """Le rival peut charger ensuite : la place est prise."""
        monkeypatch.setattr(adaptateur, "_place_kept", True)
        assert adaptateur.a_card_is_usable() is True

    def test_without_a_card_nothing_is_usable(self, monkeypatch):
        monkeypatch.setattr(adaptateur, "a_card_answers", lambda: False)
        assert adaptateur.a_card_is_usable() is False


class TestGarderLaPlace:
    @pytest.fixture(autouse=True)
    def sans_memoire(self, monkeypatch):
        """La place gardée et la réponse du pilote sont retenues : on repart de zéro."""
        adaptateur.a_card_answers.cache_clear()
        monkeypatch.setattr(adaptateur, "_place_kept", False)

    @pytest.fixture
    def sherpa_muet(self, monkeypatch):
        """Le modèle pèse cent mégaoctets : ici on compte les ouvertures."""
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
        """Avant la première installation des modèles, il n'y a rien à ouvrir."""
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
