"""The source registry, in a file, and the tokens outside the repository.

What is not registered does not exist. A token never sits in the registry: it
comes from the environment, from the keychain, or from the tokens file the
window writes, which belongs to the user alone (mode 600) and sits next to
the registry, never in a repository.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

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
    """Keeps a token under the name the registry gives it, for this user only."""
    kept = stored_tokens(file)
    if secret.strip():
        kept[name] = secret.strip()
    else:
        kept.pop(name, None)
    lines = ["# Les jetons déposés depuis la fenêtre. Ce fichier n'appartient qu'à vous.",
             "[jetons]"]
    for key, value in sorted(kept.items()):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key} = "{escaped}"')
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name == "posix":
        file.chmod(stat.S_IRUSR | stat.S_IWUSR)

def _from_the_keychain(service: str) -> str:
    """The generic password from the macOS keychain."""
    if platform.system() != "Darwin" or shutil.which("security") is None:
        return ""
    done = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True, text=True, check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""
