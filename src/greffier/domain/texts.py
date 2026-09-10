"""What is left of a text when a filesystem will not take it as is."""

from __future__ import annotations

import hashlib


def short_voiceprint(text: str) -> str:
    """A stable identifier derived from the text, when shortening is needed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
