#!/usr/bin/env python3
"""Ouvre la vraie fenêtre, affiche chaque onglet, et rend compte.

Sert la preuve Linux de l'interface (`outils/preuve-fenetre-linux.Dockerfile`),
et se lance aussi bien à la main sur n'importe quel système :

    .venv/bin/python outils/preuve_fenetre.py

La fenêtre est **construite pour de vrai**, puis chaque onglet est affiché par
son propre code — la méthode déjà retenue sur macOS, qui pilote la fenêtre plutôt
que de simuler des clics sur des coordonnées écran, trop fragiles. Rien n'est
simulé ici : si Tk manque, si la palette échoue, si un onglet lève une exception
à la peinture, ce script s'arrête en erreur.

Ce qu'il ne prouve pas : que la fenêtre est *belle*. Il prouve qu'elle s'ouvre,
se peint et change d'onglet sans exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))


def main() -> int:
    import tkinter as tk

    from greffier.config import Config
    from greffier.interface.fenetre import Fenetre

    print("tkinter", tk.TkVersion, "— Tcl", tk.TclVersion)

    fenetre = Fenetre(Config())
    # Une passe de boucle d'événements : sans elle, rien n'est encore peint et
    # une exception de peinture passerait inaperçue.
    fenetre.racine.update()
    largeur = fenetre.racine.winfo_width()
    hauteur = fenetre.racine.winfo_height()
    print(f"fenêtre ouverte : {largeur}x{hauteur}")

    intitules = list(fenetre.onglets._pages)
    for intitule in intitules:
        fenetre.onglets.montrer(intitule)
        fenetre.racine.update()
        page = fenetre.onglets._pages[intitule]
        print(f"  onglet « {intitule} » peint — {len(page.winfo_children())} éléments")

    fenetre.racine.destroy()
    print(f"{len(intitules)} onglets peints sans exception")
    return 0


if __name__ == "__main__":
    sys.exit(main())
