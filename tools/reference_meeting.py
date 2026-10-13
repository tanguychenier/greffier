"""Copy the exact, versioned release recording after checking its manifest."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def copy_reference(root: Path) -> Path:
    source = Path(__file__).resolve().parent / "fixtures/reference-meeting"
    manifest = json.loads((source / "manifest.json").read_text("utf-8"))
    for name in ("synthetic-meeting.wav", "synthetic-meeting.timeline.json"):
        recording = source / name
        if hashlib.sha256(recording.read_bytes()).hexdigest() != manifest["sha256"][name]:
            raise RuntimeError("The reference recording or timeline differs from its manifest.")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("synthetic-meeting.wav", "synthetic-meeting.timeline.json"):
        shutil.copy2(source / name, root / name)
    return root / "synthetic-meeting.wav"
