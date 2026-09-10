"""Le registre des sujets, dans un fichier qu'on relit à la main.

Le rapprochement entre « Oasis », « esup-oasis » et « le projet Oasis » ne se
devine pas : il s'apprend une fois, et il faut donc pouvoir l'écrire. Ce fichier
est aussi le seul endroit qui dit **où** vit la carte d'un sujet — sans lui,
chaque réunion en créerait une nouvelle.

À côté de `contexte.toml`, et pour les mêmes raisons : ce sont deux registres
tenus par un humain, qui grossissent, se relisent et se partagent.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from greffier.domain.subjects import Registry, Subject

GABARIT = '''# Les sujets que Greffier suit, et où vit la carte de chacun.
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
    """Le registre écrit à la main. Vide si le fichier n'existe pas.

    Une entrée mal formée est écartée sans faire échouer la lecture : un
    registre à moitié valable vaut mieux qu'une réunion qui refuse de démarrer.
    """
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
        nouvelles = (
            tuple(str(x).strip() for x in alias if str(x).strip())
            if isinstance(alias, list) else ()
        )
        precedent = fondus.get(name.casefold())
        if precedent is not None:
            nouvelles = tuple(dict.fromkeys(precedent.alias + nouvelles))
        fondus[name.casefold()] = Subject(
            name=name,
            alias=nouvelles,
            board=str(input.get("carte", "")).strip()
            or (precedent.board if precedent else ""),
        )
    return Registry(list(fondus.values()))

def lay_the_template(file: Path) -> bool:
    """Écrit le fichier d'exemple s'il n'existe pas. Vrai s'il a été créé."""
    if file.exists():
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(GABARIT, encoding="utf-8")
    return True

def noter_la_carte(file: Path, subject: str, board: str) -> bool:
    """Inscrit l'identifiant de carte d'un sujet, en ajout seul.

    Ajout et non réécriture : le fichier porte des commentaires et un ordre
    voulus. Si le sujet existe déjà avec une carte, on ne touche à rien — deux
    cartes pour un sujet est exactement ce qu'on cherche à éviter, et écraser
    la première ferait perdre la trace de celle qui existe.
    """
    registre = read(file)
    connu = registre.by_name(subject)
    if connu is not None and connu.board:
        return False
    lay_the_template(file)
    with file.open("a", encoding="utf-8") as flux:
        if connu is None:
            flux.write(f'\n[[sujets]]\nnom = "{subject}"\ncarte = "{board}"\n')
        else:
            flux.write(
                f'\n[[sujets]]\nnom = "{connu.name}"\n'
                f'alias = {list(connu.alias)!r}\ncarte = "{board}"\n'
            )
    return True
