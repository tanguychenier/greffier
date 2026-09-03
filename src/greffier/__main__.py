"""Permet « python -m greffier », dont la veille a besoin.

Elle est lancée détachée avec l'interpréteur courant plutôt qu'avec le script
« greffier » : celui-ci n'est pas toujours dans le PATH du processus qui démarre
l'enregistrement, en particulier quand l'ordre vient de l'icône de la barre de
menus.
"""

from greffier.cli import application

if __name__ == "__main__":
    application()
