"""Reads the working setting's context from a file a human maintains."""

from __future__ import annotations

import tomllib
from pathlib import Path

from greffier.domain.context import Context, Speaker_, Term

GABARIT = '''# Ce que Greffier doit savoir de votre milieu de travail.
#
# Sans ce fichier, la transcription rend le mot le plus proche qu'elle connaît :
# « déploiement » devient « exploitement », « comptes rendus » devient
# « prochains délits ». Ces mots ne sont nulle part dans ce qu'un modèle a
# appris — il faut les lui dire.
#
# « ecriture » est ce qui doit s'écrire ; « sens » ne sert pas à la
# transcription mais évite au compte rendu de laisser un sigle nu.

[[termes]]
ecriture = "OTP"
sens = "mot de passe à usage unique"

# [[termes]]
# ecriture = "CASA"
# sens = "la plateforme de gestion des logements"

# Les personnes dont le nom se prononce en réunion. Celles de la banque de voix
# sont déjà connues : inutile de les répéter ici, sauf pour donner leur rôle.
# [[personnes]]
# nom = "Sophie"
# role = "cheffe de projet"
'''


def read(file: Path) -> Context:
    """The context written by hand. Empty when the file is missing."""
    if not file.exists():
        return Context()
    try:
        content = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Context()

    termes = []
    for input in content.get("termes", []):
        if isinstance(input, dict) and str(input.get("ecriture", "")).strip():
            termes.append(Term(str(input["ecriture"]).strip(),
                                str(input.get("sens", "")).strip()))
    gens = []
    for input in content.get("personnes", []):
        if isinstance(input, dict) and str(input.get("nom", "")).strip():
            gens.append(Speaker_(str(input["nom"]).strip(),
                                    str(input.get("role", "")).strip()))
    return Context(tuple(termes), tuple(gens))


def from_vocabulary(words: list[str]) -> Context:
    """The vocabulary from config.toml, as terms without meanings."""
    return Context(tuple(Term(word.strip()) for word in words if word.strip()))


def from_the_bank(names: list[str]) -> Context:
    """The regulars, as speakers without a role."""
    return Context(intervenants=tuple(Speaker_(name.strip())
                                       for name in names if name.strip()))


def add_a_term(file: Path, ecriture: str, sens: str = "") -> bool:
    """Appends a term to the file. False when it is already there."""
    nu = ecriture.strip()
    if not nu:
        return False
    if any(t.ecriture.casefold() == nu.casefold() for t in read(file).termes):
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        lay_the_template(file)
    lines = [f'\n[[termes]]\necriture = "{nu}"\n']
    if sens.strip():
        lines.append(f'sens = "{sens.strip()}"\n')
    with file.open("a", encoding="utf-8") as stream:
        stream.write("".join(lines))
    return True


def add_a_person(file: Path, name: str, role: str = "") -> bool:
    """Appends a person to the file."""
    nu = name.strip()
    if not nu:
        return False
    if any(i.name.casefold() == nu.casefold() for i in read(file).intervenants):
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        lay_the_template(file)
    lines = [f'\n[[personnes]]\nnom = "{nu}"\n']
    if role.strip():
        lines.append(f'role = "{role.strip()}"\n')
    with file.open("a", encoding="utf-8") as stream:
        stream.write("".join(lines))
    return True


def lay_the_template(file: Path) -> bool:
    """Writes the example file when it does not exist."""
    if file.exists():
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(GABARIT, encoding="utf-8")
    return True
