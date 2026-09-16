"""The registry of language profiles."""

from __future__ import annotations

from greffier.domain.language import LanguageProfile
from greffier.domain.profiles.french import FRENCH
from greffier.domain.profiles.neutral import NEUTRAL

REGISTRY: dict[str, LanguageProfile] = {FRENCH.code: FRENCH}


def pour(code: str | None) -> LanguageProfile:
    """The profile of a language, or the neutral one."""
    return REGISTRY.get((code or "").strip().lower(), NEUTRAL)
