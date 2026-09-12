"""What a machine must carry for an integration test to mean anything.

Six files asked the same two questions -- can this machine transcribe, can it
speak -- and both answers were written for macOS: whisper.cpp and « say ».
Elsewhere the engine is faster-whisper and the voice is the VITS the installer
already lays down, so the answers were not merely absent, they were wrong: the
whole chain skipped on the machine that runs it every day.

Asked here, once, and read from the settings rather than from the system: a
machine that has moved its models is still answered correctly.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


def voices_are_out_of_reach(timbres: int = 2) -> str | None:
    """The reason to skip, or None when this machine can synthesise a meeting."""
    from make_meeting import SID_VITS, synthesis_engine

    engine = synthesis_engine()
    if engine is None:
        return ("aucune synthèse vocale : « say » sur macOS, sinon la voix de "
                "l'assistant (« python3 tools/install.py »), et ffmpeg dans les deux cas")
    if engine == "vits" and timbres > len(SID_VITS):
        return (f"{timbres} timbres demandés, la voix installée en porte "
                f"{len(SID_VITS)} : cette réunion-là demande « say »")
    return None


def the_called_name_is_out_of_reach() -> str | None:
    """Whether a first name opening a sentence survives synthesis and transcription.

    The assistant only speaks when it hears its own name, so these tests measure
    the round trip before they measure anything else. « say » carries it. The
    French VITS does not, reliably: measured four times on « Lucie, où en est la
    recette ? », it came back « UCI » once -- once is enough to make a test that
    passes three times out of four, which is worse than a test that says why it
    is not running.
    """
    hors_de_portee = voices_are_out_of_reach(2)
    if hors_de_portee:
        return hors_de_portee
    from make_meeting import synthesis_engine

    if synthesis_engine() != "say":
        return ("le prénom qui ouvre une phrase n'est pas rendu de façon sûre par la "
                "voix installée : cette famille-là demande « say »")
    return None


def transcription_is_out_of_reach(config) -> str | None:
    """The reason to skip, or None when this machine can put the chain through."""
    diarisation = config.paths.models / "diarisation"
    absents = [name for name, path in (
        ("empreintes vocales", diarisation / "nemo_en_titanet_large.onnx"),
        ("segmentation", diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"),
    ) if not path.exists()]
    if absents:
        return f"modèles absents ({', '.join(absents)}) : lance tools/install.py"
    if config.transcription.engine == "whisper.cpp":
        if not (config.paths.models / "ggml-large-v3-turbo.bin").exists():
            return "modèle whisper.cpp absent, lance tools/install.py"
        if not shutil.which("whisper-cli"):
            return "whisper.cpp absent"
        return None
    return _faster_whisper_is_out_of_reach(config.transcription.model)


def _faster_whisper_is_out_of_reach(model: str) -> str | None:
    """Looked up in the cache, never downloaded.

    A test that fetches 1.5 GB on a machine that does not have it is not a test,
    it is a surprise: it would hang for minutes, then measure the network.
    """
    if Path(model).is_dir():
        return None
    try:
        from faster_whisper.utils import _MODELS
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return "faster-whisper n'est pas installé"
    depot = _MODELS.get(model, model)
    if try_to_load_from_cache(depot, "model.bin") is None:
        return f"modèle « {model} » absent du cache, lance tools/install.py"
    return None
