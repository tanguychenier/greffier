"""The languages the tool accepts, and what it can do in each."""

from __future__ import annotations

LANGUAGES: tuple[tuple[str, str], ...] = (
    ("fr", "Français"), ("", "Détection automatique"), ("en", "Anglais"),
    ("es", "Espagnol"), ("de", "Allemand"), ("it", "Italien"),
    ("pt", "Portugais"), ("nl", "Néerlandais"), ("ca", "Catalan"),
    ("pl", "Polonais"), ("ro", "Roumain"), ("ru", "Russe"),
    ("tr", "Turc"), ("ar", "Arabe"), ("zh", "Chinois"), ("ja", "Japonais"),
)

_NAMES = dict(LANGUAGES)

def name_of(code: str) -> str:
    """The name of a language, or the code itself when unknown."""
    return _NAMES.get(code, code)

def eprouvee(code: str) -> bool:
    """Whether first-name recognition is genuinely served in this language."""
    from greffier.domain import profiles

    return profiles.pour(code).eprouve

def label_text(code: str) -> str:
    """What to show next to a language, without euphemism."""
    name = name_of(code)
    if not code or eprouvee(code):
        return name
    return f"{name} — voix à nommer à la main"
