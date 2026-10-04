"""The source registry, in a file, and the tokens outside the repository.

What is not registered does not exist. A token never sits in the registry: it
comes from the environment, from the keychain, or from the tokens file the
window writes, which belongs to the user alone (mode 600) and sits next to
the registry, never in a repository.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from greffier.adapters.private_files import write_private_text
from greffier.domain.sources import Kind, Registry, Right, Source
from greffier.locations import config_folder

TEMPLATE = '''# Les sources extérieures que Greffier a le droit de consulter.
#
# Ce qui n'est pas ici n'existe pas pour l'outil : il ne découvre aucun projet
# de lui-même. C'est ce qui borne le risque à ce que vous avez listé.
#
# « droit » vaut « lecture » ou « écriture ». La lecture seule est le défaut.
# Une écriture demande toujours confirmation, même sur une source autorisée.
#
# « jeton » nomme **où** trouver le secret, jamais le secret :
#   jeton = "GREFFIER_GITLAB_JETON"        une variable d'environnement, ou
#                                          une entrée du fichier des jetons
#                                          (onglet Réglages ▸ Sources)
#   jeton = "trousseau:greffier-gitlab"    une entrée du trousseau macOS
#
# Pour déposer un jeton dans le trousseau :
#   security add-generic-password -a "$USER" -s greffier-gitlab -w

# [[sources]]
# nom = "recherche"
# genre = "gitlab"
# adresse = "https://gitlab.example.fr"
# projet = "equipe/outil"
# droit = "lecture"
# jeton = "trousseau:greffier-gitlab"

# [[sources]]
# nom = "suivi"
# genre = "jira"
# adresse = "https://exemple.atlassian.net"
# projet = "PROJ"
# droit = "lecture"
# jeton = "trousseau:greffier-jira"
'''

KEYCHAIN_PREFIX = "trousseau:"

#: What a TOML key may be written bare; anything else is quoted.
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")

#: The characters a TOML basic string escapes by a letter; every other control
#: character, U+0000..U+001F and U+007F, goes as \uXXXX.
_SHORT_ESCAPES = {
    "\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t",
    "\n": "\\n", "\f": "\\f", "\r": "\\r",
}

def read(file: Path) -> Registry:
    """The registered sources. Empty when the file does not exist."""
    if not file.exists():
        return Registry([])
    try:
        content = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Registry([])

    sources: list[Source] = []
    for input in content.get("sources", []):
        if not isinstance(input, dict):
            continue
        try:
            sources.append(Source(
                name=str(input.get("nom", "")).strip(),
                kind=Kind(str(input.get("genre", "")).strip().casefold()),
                address=str(input.get("adresse", "")).strip().rstrip("/"),
                project=str(input.get("projet", "")).strip(),
                right=Right(str(input.get("droit", "lecture")).strip().casefold()),
                token=str(input.get("jeton", "")).strip(),
            ))
        except ValueError:
            continue
    return Registry(sources)

def lay_the_template(file: Path) -> bool:
    """Writes the example file when it does not exist."""
    if file.exists():
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(TEMPLATE, encoding="utf-8")
    return True

def tokens_file() -> Path:
    """Where the window puts a token pasted into it: next to the registry."""
    return config_folder() / "jetons.toml"

def token_for(source: Source, file: Path | None = None) -> str:
    """This source's secret, read where the registry says.

    A name that is not a keychain entry is looked up in the environment first,
    then in the tokens file: the environment is where a terminal puts it, the
    file where the window does.
    """
    if not source.token:
        return ""
    if source.token.startswith(KEYCHAIN_PREFIX):
        return _from_the_keychain(source.token[len(KEYCHAIN_PREFIX):])
    from_environment = os.environ.get(source.token, "").strip()
    if from_environment:
        return from_environment
    return stored_tokens(file or tokens_file()).get(source.token, "")

def stored_tokens(file: Path) -> dict[str, str]:
    """The tokens the window stored, by the name the registry gives them."""
    if not file.exists():
        return {}
    try:
        content = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    kept = content.get("jetons", {})
    if not isinstance(kept, dict):
        return {}
    return {str(k): str(v).strip() for k, v in kept.items() if str(v).strip()}

def store_token(file: Path, name: str, secret: str) -> None:
    """Keeps a token under the name the registry gives it, for this user only.

    The value goes in as a TOML basic string, control characters included: a
    key pasted with its line breaks, CRLF from a Windows clipboard included,
    used to leave a file tomllib refused, and `stored_tokens` then gave back
    nothing at all, every token lost at once. The name is quoted when TOML
    does not allow it bare rather than refused: it comes from the registry the
    person wrote by hand, and a refusal here would surface as a crash in the
    window long after the registry was written, while a quoted key reads back
    under the very same name.
    """
    kept = stored_tokens(file)
    if secret.strip():
        kept[name] = secret.strip()
    else:
        kept.pop(name, None)
    lines = ["# Les jetons déposés depuis la fenêtre. Ce fichier n'appartient qu'à vous.",
             "[jetons]"]
    for key, value in sorted(kept.items()):
        lines.append(f"{_toml_key(key)} = {_basic_string(value)}")
    write_private_text(file, "\n".join(lines) + "\n")

def _toml_key(name: str) -> str:
    """`name` as it is when TOML allows it bare, as a quoted key otherwise."""
    return name if _BARE_KEY.fullmatch(name) else _basic_string(name)

def _basic_string(text: str) -> str:
    """`text` as a TOML basic string, every control character escaped."""
    return '"' + "".join(_escaped(character) for character in text) + '"'

def _escaped(character: str) -> str:
    if character in _SHORT_ESCAPES:
        return _SHORT_ESCAPES[character]
    if ord(character) < 0x20 or ord(character) == 0x7F:
        return f"\\u{ord(character):04X}"
    return character

def _from_the_keychain(service: str) -> str:
    """The generic password from the macOS keychain."""
    if platform.system() != "Darwin" or shutil.which("security") is None:
        return ""
    done = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True, text=True, check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""
