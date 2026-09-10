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


def capturer(window: object, target: Path) -> bool:
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
    racine = window.racine  # type: ignore[attr-defined]
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
    width = racine.winfo_width() + 2 * marge
    height = racine.winfo_height() + 2 * marge
    target.parent.mkdir(parents=True, exist_ok=True)
    fait = subprocess.run(
        ["screencapture", "-x", "-o", f"-R{x},{y},{width},{height}", str(target)],
        check=False, capture_output=True,
    )
    return fait.returncode == 0 and target.exists()


def main() -> int:
    import tkinter as tk

    from greffier.adapters.configuration import Config
    from greffier.interface.window import Window

    print("tkinter", tk.TkVersion, "— Tcl", tk.TclVersion)

    window = Window(Config())
    # Une passe de boucle d'événements : sans elle, rien n'est encore peint et
    # une exception de peinture passerait inaperçue.
    window.racine.update()
    width = window.racine.winfo_width()
    height = window.racine.winfo_height()
    print(f"fenêtre ouverte : {width}x{height}")

    intitules = list(window.tabs._pages)
    for caption in intitules:
        window.tabs.reveal(caption)
        window.racine.update()
        page = window.tabs._pages[caption]
        print(f"  onglet « {caption} » peint — {len(page.winfo_children())} éléments")

    # La pastille de compte se dessine hors des tests : elle touche Tk, qui ne
    # démarre pas sur un exécuteur d'intégration continue. C'est donc ici qu'on
    # vérifie qu'elle s'affiche, élargit son onglet, et s'efface à l'ouverture.
    window.tabs.reveal(intitules[0])
    target = "Conversation" if "Conversation" in intitules else intitules[-1]
    segment = window.tabs._segments[target]
    nue = int(segment.cget("width"))
    window.tabs.mark(target, 3)
    window.racine.update()
    avec = int(segment.cget("width"))
    marques = [
        segment.itemcget(item, "text")
        for item in segment.find_all()
        if segment.type(item) == "text"
    ]
    if avec <= nue or "3" not in marques:
        print(f"  ✗ pastille non dessinée sur « {target} » ({nue} → {avec}, {marques})")
        window.racine.destroy()
        return 1
    print(f"  pastille sur « {target} » : {nue} → {avec} px, marque {marques[-1]}")
    window.tabs.reveal(target)
    window.racine.update()
    if int(segment.cget("width")) != nue:
        print("  ✗ la pastille survit à l'ouverture de son onglet")
        window.racine.destroy()
        return 1
    print("  pastille effacée à l'ouverture de l'onglet")

    # Une capture par onglet, à la largeur minimale **et** à une largeur
    # confortable : c'est étroit que les barres de boutons débordent, et large
    # qu'on voit si elles s'aèrent correctement.
    if "--capturer" in sys.argv:
        folder = Path(
            sys.argv[sys.argv.index("--capturer") + 1]
            if len(sys.argv) > sys.argv.index("--capturer") + 1
            else "/tmp/greffier-captures"
        )
        for width, name in ((880, "etroit"), (1280, "large")):
            for caption in intitules:
                # La géométrie est réaffirmée à **chaque** onglet : changer
                # d'onglet change le contenu, et la fenêtre se rétablit sur ce
                # que ce contenu demande. Fixée une seule fois en tête de
                # boucle, elle valait encore pour la première capture et plus
                # pour les suivantes — des images tronquées, dont on cherche le
                # défaut dans l'interface au lieu de l'outil.
                window.racine.geometry(f"{width}x760")
                window.tabs.reveal(caption)
                window.racine.update()
                without_accents = (
                    caption.lower().replace(" ", "-").replace("é", "e")
                )
                target = folder / f"{name}-{without_accents}.png"
                if capturer(window, target):
                    print(f"  capture {target}")
                else:
                    print("  capture indisponible sur ce système")
                    break

    window.racine.destroy()
    print(f"{len(intitules)} onglets peints sans exception")
    return 0


if __name__ == "__main__":
    sys.exit(main())
