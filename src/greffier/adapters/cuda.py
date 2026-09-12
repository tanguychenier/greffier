"""What CUDA needs to be found, and whether a card answers at all.

The `nvidia-*` wheels lay their libraries in the packages folder, outside the
path the loader looks in. Neither CTranslate2 nor onnxruntime finds them there:
both fall back on the processor without saying a word. Loading them once, with
`RTLD_GLOBAL`, is enough for everything that comes after to find them already
open -- and it is the only way that survives a desktop shortcut, which sets no
`LD_LIBRARY_PATH`.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib.util
import sys
from functools import cache
from pathlib import Path

from greffier.domain.arithmetic import CARD

LIBRARIES = (
    "cublas/lib/libcublasLt.so*",
    "cublas/lib/libcublas.so*",
    "cudnn/lib/libcudnn*.so*",
    "cuda_nvrtc/lib/libnvrtc.so*",
    "cuda_runtime/lib/libcudart.so*",
    "cufft/lib/libcufft.so*",
    "curand/lib/libcurand.so*",
)

def libraries() -> list[Path]:
    """The libraries the nvidia wheels install, in dependency order.

    cuBLAS looks for cuBLASLt while it loads: the other way round it would not
    find it, and the card would be lost for a missing ordering.
    """
    package = importlib.util.find_spec("nvidia")
    if package is None or not package.submodule_search_locations:
        return []
    root = Path(next(iter(package.submodule_search_locations)))
    return [path for motif in LIBRARIES for path in sorted(root.glob(motif))]

def show_to_the_loader() -> None:
    """Loads what libraries() found, and keeps going when one refuses.

    A library that will not load costs the card, not the meeting: everything
    downstream falls back on the processor.
    """
    for path in libraries():
        with contextlib.suppress(OSError):
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)

@cache
def a_card_answers() -> bool:
    """Whether the driver is installed and at least one card replies.

    Asking the driver rather than looking for `nvidia-smi`: a machine can carry
    the tool without a usable card, and a container can carry the card without
    the tool.
    """
    try:
        driver = ctypes.CDLL("libcuda.so.1")
    except OSError:
        return False
    with contextlib.suppress(AttributeError, OSError):
        if driver.cuInit(0) != 0:
            return False
        how_many = ctypes.c_int(0)
        if driver.cuDeviceGetCount(ctypes.byref(how_many)) != 0:
            return False
        return how_many.value > 0
    return False


def another_runtime_is_open() -> bool:
    """Whether a second ONNX Runtime is already loaded in this process.

    faster-whisper brings its own along with its voice detector. Two of them
    cannot share a process: the one that opens second binds to the other's
    symbols and either reads a corrupt graph or, when the versions are close
    enough to bind cleanly, kills the interpreter. Both measured. Whichever
    opens first wins, and the loser falls back on the processor rather than
    taking the meeting down with it.
    """
    return "onnxruntime" in sys.modules

def a_card_is_usable() -> bool:
    """A card the driver answers for, and a runtime that got in first.

    Once the place has been kept, the rival runtime may load: it arrived
    second, and the card stays ours for the rest of the process.
    """
    return a_card_answers() and (_place_kept or not another_runtime_is_open())

def keep_the_place(model: Path) -> None:
    """Opens a session on the card and drops it, so this runtime is the first in.

    Called before anything can load the rival runtime. Measured at 1.15 s, and
    it leaves the driver context alone on the card -- 85 MB, freed with the
    process.
    """
    global _place_kept
    if _place_kept or not a_card_is_usable() or not model.exists():
        return
    _place_kept = True
    show_to_the_loader()
    import sherpa_onnx

    with contextlib.suppress(Exception):
        sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model), num_threads=1, provider=CARD)
        )

_place_kept = False
