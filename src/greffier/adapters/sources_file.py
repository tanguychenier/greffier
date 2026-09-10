"""The source registry, in a file, and the tokens outside the repository.

What is not registered does not exist. A token never sits in the file: it comes
from the environment or the keychain.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tomllib
from pathlib import Path

from greffier.domain.sources import Kind, Registry, Right, Source

GABARIT = '''# Les sources extérieures que Greffier a le droit de consulter.
#
# Ce qui n'est pas ici n'existe pas pour l'outil : il ne découvre aucun projet
# de lui-même. C'est ce qui borne le risque à ce que vous avez listé.
#
# « droit » vaut « lecture » ou « écriture ». La lecture seule est le défaut.
# Une écriture demande toujours confirmation, même sur une source autorisée.
#
# « jeton » nomme **où** trouver le secret, jamais le secret :
#   jeton = "GREFFIER_GITLAB_JETON"        une variable d'environnement
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

PREFIXE_TROUSSEAU = "trousseau:"

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
                adresse=str(input.get("adresse", "")).strip().rstrip("/"),
                project=str(input.get("projet", "")).strip(),
                droit=Right(str(input.get("droit", "lecture")).strip().casefold()),
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
    file.write_text(GABARIT, encoding="utf-8")
    return True

def token_for(source: Source) -> str:
    """This source's secret, read where the registry says."""
    if not source.token:
        return ""
    if source.token.startswith(PREFIXE_TROUSSEAU):
        return _from_the_keychain(source.token[len(PREFIXE_TROUSSEAU):])
    return os.environ.get(source.token, "").strip()

def _from_the_keychain(service: str) -> str:
    """The generic password from the macOS keychain."""
    if platform.system() != "Darwin" or shutil.which("security") is None:
        return ""
    done = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True, text=True, check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""
