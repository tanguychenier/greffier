"""Read DirectShow audio device names without opening an audio recording."""

from __future__ import annotations

import re
import subprocess

_AUDIO = re.compile(r'"(.+)"\s+\(audio\)\s*$')


def devices() -> tuple[str, ...]:
    try:
        found = subprocess.run(
            ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, errors="replace", check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(match.group(1) for line in found.stderr.splitlines()
                 if (match := _AUDIO.search(line)))


def input_name(configured: str) -> str:
    if configured and configured != "default":
        return configured
    inputs = devices()
    if len(inputs) == 1:
        return inputs[0]
    if not inputs:
        raise RuntimeError("Aucune entrée audio DirectShow trouvée. Vérifie ffmpeg et ton micro.")
    raise RuntimeError(
        "Plusieurs entrées audio sont disponibles. Choisis leur nom dans « audio.entree » "
        "avant d'enregistrer."
    )
