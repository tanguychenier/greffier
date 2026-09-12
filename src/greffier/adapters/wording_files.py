"""The catalogues of what the tool says, one file per language.

TOML rather than gettext: a new language is a file somebody can open, translate
and send back, with no tooling to install and no compilation step between them
and seeing their work. The cost is that nothing checks the keys -- so a test
does, comparing every catalogue against the reference.

Sections are flattened on reading: `fenetre.demarrer` in the code, `[fenetre]`
then `demarrer =` in the file, which is what makes the file readable to somebody
who does not know the code.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from greffier.domain.tongue import FALLBACK, Wording

CATALOGUES = Path(__file__).resolve().parent.parent / "wording"


def file_for(language: str) -> Path:
    return CATALOGUES / f"{language}.toml"


def translated() -> tuple[str, ...]:
    """The languages a catalogue exists for, whatever the code declares."""
    return tuple(sorted(f.stem for f in CATALOGUES.glob("*.toml")))


def _flat(read: dict[str, object], prefix: str = "") -> dict[str, str]:
    plat: dict[str, str] = {}
    for key, value in read.items():
        chemin = f"{prefix}{key}"
        if isinstance(value, dict):
            plat |= _flat(value, f"{chemin}.")
        elif isinstance(value, str):
            plat[chemin] = value
    return plat


def read(language: str) -> dict[str, str]:
    """One catalogue, flattened. Empty when there is none, never an error."""
    file = file_for(language)
    if not file.exists():
        return {}
    try:
        return _flat(tomllib.loads(file.read_text(encoding="utf-8")))
    except tomllib.TOMLDecodeError:
        # A catalogue somebody broke must cost the sentences of that language,
        # never the window itself.
        return {}


def wording(language: str) -> Wording:
    """What the tool says in this language, with the reference behind it."""
    default = read(FALLBACK)
    return Wording(language=language, says=read(language), default=default)
