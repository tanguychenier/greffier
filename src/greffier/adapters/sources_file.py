"""Le registre des sources, dans un fichier, et les jetons hors de ce fichier.

Le fichier dit **où** trouver un jeton, jamais le jeton. Deux formes acceptées :
le nom d'une variable d'environnement, ou une entrée de trousseau préfixée
« trousseau: ». Le trousseau est préférable sur macOS — il survit aux
sauvegardes du dossier de configuration sans y figurer.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tomllib
from pathlib import Path

from greffier.domain.sources import Droit, Genre, Registre, Source

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

def read(file: Path) -> Registre:
    """Les sources inscrites. Vide si le fichier n'existe pas.

    Une entrée mal formée est écartée **avec** son nom : contrairement au
    contexte, une source ignorée en silence produirait un refus incompréhensible
    plus tard — « cette source n'est pas inscrite » alors qu'elle y figure.
    """
    if not file.exists():
        return Registre([])
    try:
        content = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Registre([])

    sources: list[Source] = []
    for input in content.get("sources", []):
        if not isinstance(input, dict):
            continue
        try:
            sources.append(Source(
                name=str(input.get("nom", "")).strip(),
                kind=Genre(str(input.get("genre", "")).strip().casefold()),
                adresse=str(input.get("adresse", "")).strip().rstrip("/"),
                projet=str(input.get("projet", "")).strip(),
                droit=Droit(str(input.get("droit", "lecture")).strip().casefold()),
                token=str(input.get("jeton", "")).strip(),
            ))
        except ValueError:
            continue
    return Registre(sources)

def lay_the_template(file: Path) -> bool:
    """Écrit le fichier d'exemple s'il n'existe pas. Vrai s'il a été créé."""
    if file.exists():
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(GABARIT, encoding="utf-8")
    return True

def token_for(source: Source) -> str:
    """Le secret de cette source, lu là où le registre dit qu'il est.

    Rend une chaîne vide plutôt que de lever : l'appelant sait dire « cette
    source n'a pas de jeton utilisable » mieux qu'une exception ne le dirait, et
    un jeton absent n'est pas une panne mais un réglage à finir.
    """
    if not source.token:
        return ""
    if source.token.startswith(PREFIXE_TROUSSEAU):
        return _from_the_keychain(source.token[len(PREFIXE_TROUSSEAU):])
    return os.environ.get(source.token, "").strip()

def _from_the_keychain(service: str) -> str:
    """Le mot de passe générique du trousseau macOS, ou rien.

    Le trousseau plutôt qu'une variable : il survit aux sauvegardes du dossier
    de configuration sans y figurer, et macOS demande l'autorisation la première
    fois — ce qui est une trace de plus qu'un fichier n'offre pas.
    """
    if platform.system() != "Darwin" or shutil.which("security") is None:
        return ""
    fait = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True, text=True, check=False,
    )
    return fait.stdout.strip() if fait.returncode == 0 else ""
