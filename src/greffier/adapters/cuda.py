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
from functools import cache
from pathlib import Path

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
