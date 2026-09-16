"""The subject registry, in a file a human maintains."""

from __future__ import annotations

import tomllib
from pathlib import Path

from greffier.domain.subjects import Registry, Subject

TEMPLATE = '''# Les sujets que Greffier suit, et où vit la carte de chacun.
#
# « alias » est ce qui ne se devine pas : personne ne peut savoir
# qu'« esup-oasis » désigne le même projet qu'« Oasis ». Sans l'alias, chaque
# formulation ouvrirait une carte de plus.
#
# « carte » est renseigné par l'outil quand il crée la carte. Ne l'écris à la
# main que pour désigner un tableau existant, ce qui est la seule façon
# d'autoriser Greffier à écrire dessus.

# [[sujets]]
# nom = "Oasis"
# alias = ["esup-oasis", "le projet Oasis"]
# carte = ""
'''

def read(file: Path) -> Registry:
    """The registry written by hand. Empty when the file is missing."""
    if not file.exists():
        return Registry()
    try:
        content = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Registry()

    fondus: dict[str, Subject] = {}
    for input in content.get("sujets", []):
        if not isinstance(input, dict) or not str(input.get("nom", "")).strip():
            continue
        name = str(input["nom"]).strip()
        alias = input.get("alias", [])
        fresh = (
            tuple(str(x).strip() for x in alias if str(x).strip())
            if isinstance(alias, list) else ()
        )
        previous = fondus.get(name.casefold())
        if previous is not None:
            fresh = tuple(dict.fromkeys(previous.alias + fresh))
        fondus[name.casefold()] = Subject(
            name=name,
            alias=fresh,
            board=str(input.get("carte", "")).strip()
            or (previous.board if previous else ""),
        )
    return Registry(list(fondus.values()))

def lay_the_template(file: Path) -> bool:
    """Writes the example file when it does not exist."""
    if file.exists():
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(TEMPLATE, encoding="utf-8")
    return True

def note_the_board(file: Path, subject: str, board: str) -> bool:
    """Records a subject's board identifier, append-only."""
    the_registry = read(file)
    known_one = the_registry.by_name(subject)
    if known_one is not None and known_one.board:
        return False
    lay_the_template(file)
    with file.open("a", encoding="utf-8") as stream:
        if known_one is None:
            stream.write(f'\n[[sujets]]\nnom = "{subject}"\ncarte = "{board}"\n')
        else:
            stream.write(
                f'\n[[sujets]]\nnom = "{known_one.name}"\n'
                f'alias = {list(known_one.alias)!r}\ncarte = "{board}"\n'
            )
    return True
