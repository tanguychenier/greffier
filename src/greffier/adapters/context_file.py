"""Lit le contexte du milieu de travail dans un fichier, et le complète.

Un fichier séparé de `config.toml` : un glossaire grossit, se partage entre
collègues et se relit à la main, ce qu'un fichier de réglages régénéré à chaque
changement dans la fenêtre supporte mal — les listes du vocabulaire y restent
déjà par ce motif.

Trois sources se fondent en une, de la moins précise à la plus précise :

1. le `vocabulaire` de `config.toml`, une liste de mots sans leur sens, gardée
   pour que les postes déjà réglés ne perdent rien ;
2. la **banque de voix**, qui connaît le nom des habitués — un prénom mal
   transcrit ne se rattrape pas plus tard, et c'est lui qui décide de
   l'attribution des tours de parole ; le tenir hors de l'amorce était une
   perte gratuite ;
3. `contexte.toml`, où l'on écrit ce qu'un sigle veut dire.

Le fichier absent n'est pas une erreur : la fusion rend alors ce que les deux
premières sources savent.
"""

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
    """Le contexte écrit à la main. Vide si le fichier n'existe pas.

    Une entrée mal formée est écartée sans faire échouer la lecture : un
    glossaire à moitié valable vaut mieux qu'une réunion qui refuse de démarrer
    parce qu'une ligne manque son « ecriture ».
    """
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
    """Le vocabulaire de `config.toml`, en termes sans sens.

    Gardé pour que les postes déjà réglés ne perdent rien le jour où le fichier
    de contexte apparaît.
    """
    return Context(tuple(Term(mot.strip()) for mot in words if mot.strip()))


def from_the_bank(names: list[str]) -> Context:
    """Les habitués, en intervenants sans rôle.

    La banque de voix les connaît parce qu'on les a nommés une fois : les
    reprendre ici évite d'avoir à les réécrire dans le vocabulaire.
    """
    return Context(intervenants=tuple(Speaker_(name.strip())
                                       for name in names if name.strip()))


def add_a_term(file: Path, ecriture: str, sens: str = "") -> bool:
    """Ajoute un terme au fichier, en ajout seul. Faux s'il y était déjà.

    Ajout et non réécriture : le fichier est édité à la main, il porte des
    commentaires et un ordre voulus, et le régénérer les effacerait. C'est ce
    qui permet de répondre à une question pendant une réunion sans perdre ce
    que quelqu'un y avait écrit.
    """
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
    with file.open("a", encoding="utf-8") as flux:
        flux.write("".join(lines))
    return True


def add_a_person(file: Path, name: str, role: str = "") -> bool:
    """Ajoute une personne au fichier, en ajout seul. Faux si elle y était déjà.

    Même principe que pour un terme : on ajoute au bout plutôt que de
    régénérer, pour ne pas effacer les commentaires et l'ordre voulus.
    """
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
    with file.open("a", encoding="utf-8") as flux:
        flux.write("".join(lines))
    return True


def lay_the_template(file: Path) -> bool:
    """Écrit le fichier d'exemple s'il n'existe pas. Vrai s'il a été créé.

    Un fichier commenté vaut mieux qu'une documentation : c'est là qu'on le
    cherche, au moment où l'on en a besoin.
    """
    if file.exists():
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(GABARIT, encoding="utf-8")
    return True
