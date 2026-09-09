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

from greffier.domaine.sujets import Registre, Sujet

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


def lire(fichier: Path) -> Registre:
    """Le registre écrit à la main. Vide si le fichier n'existe pas.

    Une entrée mal formée est écartée sans faire échouer la lecture : un
    registre à moitié valable vaut mieux qu'une réunion qui refuse de démarrer.
    """
    if not fichier.exists():
        return Registre()
    try:
        contenu = tomllib.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Registre()

    # Les entrées de même nom se fondent, la dernière l'emportant : le fichier
    # s'écrit en ajout seul — pour ne pas effacer ses commentaires — donc
    # renseigner la carte d'un sujet déjà listé ajoute une seconde entrée. Sans
    # cette fusion, la première l'emporterait et la carte resterait ignorée.
    fondus: dict[str, Sujet] = {}
    for entree in contenu.get("sujets", []):
        if not isinstance(entree, dict) or not str(entree.get("nom", "")).strip():
            continue
        nom = str(entree["nom"]).strip()
        alias = entree.get("alias", [])
        nouvelles = (
            tuple(str(x).strip() for x in alias if str(x).strip())
            if isinstance(alias, list) else ()
        )
        precedent = fondus.get(nom.casefold())
        if precedent is not None:
            # Les alias s'accumulent, la carte la plus récemment écrite gagne.
            nouvelles = tuple(dict.fromkeys(precedent.alias + nouvelles))
        fondus[nom.casefold()] = Sujet(
            nom=nom,
            alias=nouvelles,
            carte=str(entree.get("carte", "")).strip()
            or (precedent.carte if precedent else ""),
        )
    return Registre(list(fondus.values()))


def poser_le_gabarit(fichier: Path) -> bool:
    """Écrit le fichier d'exemple s'il n'existe pas. Vrai s'il a été créé."""
    if fichier.exists():
        return False
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(GABARIT, encoding="utf-8")
    return True


def noter_la_carte(fichier: Path, sujet: str, carte: str) -> bool:
    """Inscrit l'identifiant de carte d'un sujet, en ajout seul.

    Ajout et non réécriture : le fichier porte des commentaires et un ordre
    voulus. Si le sujet existe déjà avec une carte, on ne touche à rien — deux
    cartes pour un sujet est exactement ce qu'on cherche à éviter, et écraser
    la première ferait perdre la trace de celle qui existe.
    """
    registre = lire(fichier)
    connu = registre.par_nom(sujet)
    if connu is not None and connu.carte:
        return False
    poser_le_gabarit(fichier)
    with fichier.open("a", encoding="utf-8") as flux:
        if connu is None:
            flux.write(f'\n[[sujets]]\nnom = "{sujet}"\ncarte = "{carte}"\n')
        else:
            # Le sujet existe sans carte : on ajoute une entrée qui la porte,
            # et la lecture retiendra la dernière. Réécrire le fichier pour
            # modifier une ligne effacerait les commentaires alentour.
            flux.write(
                f'\n[[sujets]]\nnom = "{connu.nom}"\n'
                f'alias = {list(connu.alias)!r}\ncarte = "{carte}"\n'
            )
    return True
