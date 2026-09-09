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


def capturer(fenetre: object, cible: Path) -> bool:
    """Photographie la fenêtre, pour qu'on puisse la **regarder**.

    Les tests disent qu'un onglet se peint sans exception ; ils ne disent pas
    qu'un bouton sort du cadre. Deux boutons ont ainsi été ajoutés à l'onglet
    Réunions sans que personne ne voie que le septième dépassait de la fenêtre,
    invisible et inatteignable. Une capture coûte une seconde et le montre.

    macOS seulement : `screencapture` sait viser une région de l'écran. Ailleurs,
    rend Faux sans se plaindre — la preuve de peinture, elle, marche partout.
    """
    import shutil
    import subprocess
    import sys as _sys
    import time

    if _sys.platform != "darwin" or shutil.which("screencapture") is None:
        return False
    racine = fenetre.racine  # type: ignore[attr-defined]
    # Devant, et devant tout le reste. `screencapture -R` photographie une
    # **région de l'écran**, pas une fenêtre : la première version de cet outil
    # a rendu une capture de la messagerie qui se trouvait à cet endroit, la
    # fenêtre de Greffier étant passée derrière pendant l'attente. On ne
    # regardait donc pas ce qu'on croyait regarder, ce qui est pire que de ne
    # pas regarder.
    racine.lift()
    racine.attributes("-topmost", True)
    # Deux passes et une pause : `update` vide la file d'événements de Tk, mais
    # macOS composite ensuite, de façon asynchrone. Une capture prise juste
    # après un redimensionnement montrait la fenêtre à moitié redessinée —
    # barre de boutons absente alors qu'elle était bien placée, ce qui envoie
    # chercher un défaut d'interface qui n'existe pas.
    racine.update()
    time.sleep(0.4)
    racine.update()
    # Les coordonnées **après** la pause : prises avant, elles datent d'avant
    # le redimensionnement et la capture cadre à côté.
    # Un peu large : l'ombre portée de la fenêtre déborde de sa géométrie, et
    # une capture au pixel près coupe le bord droit, celui qui pose problème.
    marge = 24
    x = racine.winfo_rootx() - marge
    y = racine.winfo_rooty() - marge
    largeur = racine.winfo_width() + 2 * marge
    hauteur = racine.winfo_height() + 2 * marge
    cible.parent.mkdir(parents=True, exist_ok=True)
    fait = subprocess.run(
        ["screencapture", "-x", "-o", f"-R{x},{y},{largeur},{hauteur}", str(cible)],
        check=False, capture_output=True,
    )
    return fait.returncode == 0 and cible.exists()


def main() -> int:
    import tkinter as tk

    from greffier.adaptateurs.configuration import Config
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

    # La pastille de compte se dessine hors des tests : elle touche Tk, qui ne
    # démarre pas sur un exécuteur d'intégration continue. C'est donc ici qu'on
    # vérifie qu'elle s'affiche, élargit son onglet, et s'efface à l'ouverture.
    fenetre.onglets.montrer(intitules[0])
    cible = "Conversation" if "Conversation" in intitules else intitules[-1]
    segment = fenetre.onglets._segments[cible]
    nue = int(segment.cget("width"))
    fenetre.onglets.marquer(cible, 3)
    fenetre.racine.update()
    avec = int(segment.cget("width"))
    marques = [
        segment.itemcget(item, "text")
        for item in segment.find_all()
        if segment.type(item) == "text"
    ]
    if avec <= nue or "3" not in marques:
        print(f"  ✗ pastille non dessinée sur « {cible} » ({nue} → {avec}, {marques})")
        fenetre.racine.destroy()
        return 1
    print(f"  pastille sur « {cible} » : {nue} → {avec} px, marque {marques[-1]}")
    fenetre.onglets.montrer(cible)
    fenetre.racine.update()
    if int(segment.cget("width")) != nue:
        print("  ✗ la pastille survit à l'ouverture de son onglet")
        fenetre.racine.destroy()
        return 1
    print("  pastille effacée à l'ouverture de l'onglet")

    # Une capture par onglet, à la largeur minimale **et** à une largeur
    # confortable : c'est étroit que les barres de boutons débordent, et large
    # qu'on voit si elles s'aèrent correctement.
    if "--capturer" in sys.argv:
        dossier = Path(
            sys.argv[sys.argv.index("--capturer") + 1]
            if len(sys.argv) > sys.argv.index("--capturer") + 1
            else "/tmp/greffier-captures"
        )
        for largeur, nom in ((880, "etroit"), (1280, "large")):
            for intitule in intitules:
                # La géométrie est réaffirmée à **chaque** onglet : changer
                # d'onglet change le contenu, et la fenêtre se rétablit sur ce
                # que ce contenu demande. Fixée une seule fois en tête de
                # boucle, elle valait encore pour la première capture et plus
                # pour les suivantes — des images tronquées, dont on cherche le
                # défaut dans l'interface au lieu de l'outil.
                fenetre.racine.geometry(f"{largeur}x760")
                fenetre.onglets.montrer(intitule)
                fenetre.racine.update()
                sans_accent = (
                    intitule.lower().replace(" ", "-").replace("é", "e")
                )
                cible = dossier / f"{nom}-{sans_accent}.png"
                if capturer(fenetre, cible):
                    print(f"  capture {cible}")
                else:
                    print("  capture indisponible sur ce système")
                    break

    fenetre.racine.destroy()
    print(f"{len(intitules)} onglets peints sans exception")
    return 0


if __name__ == "__main__":
    sys.exit(main())
