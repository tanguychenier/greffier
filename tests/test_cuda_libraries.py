"""Comment les bibliothèques CUDA sont montrées au chargeur du système.

Les roues « nvidia-cublas-cu12 » et « nvidia-cudnn-cu12 » posent leurs
bibliothèques dans le dossier des paquets, hors du chemin où le chargeur va les
chercher. CTranslate2 ne les y trouve pas et se rabat sur le processeur, treize
fois plus lent — sans rien dire. La seule autre façon de les lui montrer serait
de régler `LD_LIBRARY_PATH` avant de lancer Greffier, ce qu'aucun raccourci de
bureau ne fait.
"""

from types import SimpleNamespace

import pytest

from greffier.adapters import transcription_faster_whisper as adaptateur


@pytest.fixture
def roues(monkeypatch, tmp_path):
    """Un dossier « nvidia » garni comme le font les roues."""
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
    def test_toutes_les_bibliotheques_sont_rendues(self, roues):
        names = [path.name for path in adaptateur.cuda_libraries()]
        assert set(names) == {"libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9",
                             "libcudnn_graph.so.9", "libnvrtc.so.12"}

    def test_cublaslt_vient_avant_cublas(self, roues):
        """cuBLAS en dépend : chargée la première, elle ne la trouverait pas."""
        names = [path.name for path in adaptateur.cuda_libraries()]
        assert names.index("libcublasLt.so.12") < names.index("libcublas.so.12")

    def test_sans_les_roues_il_n_y_a_rien_a_charger(self, monkeypatch):
        """Le cas ordinaire : elles ne servent qu'à une carte NVIDIA."""
        monkeypatch.setattr(adaptateur.importlib.util, "find_spec", lambda _name: None)
        assert adaptateur.cuda_libraries() == []

    def test_un_paquet_sans_dossier_ne_fait_pas_echouer(self, monkeypatch):
        monkeypatch.setattr(
            adaptateur.importlib.util, "find_spec",
            lambda _name: SimpleNamespace(submodule_search_locations=None),
        )
        assert adaptateur.cuda_libraries() == []


class TestChargement:
    def test_une_bibliotheque_illisible_n_arrete_pas_la_transcription(self, roues):
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
