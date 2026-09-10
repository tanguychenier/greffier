#!/usr/bin/env python3
"""Point d'entrée de l'exécutable Windows.

PyInstaller a besoin d'un script à empaqueter, et `python -m greffier fenetre`
n'en est pas un. Ce fichier ne fait rien d'autre que ce que ferait cette
commande, avec trois précautions que l'exécutable impose et que la ligne de
commande n'a pas :

- **rendre la main sur `--version`.** Un exécutable graphique lancé sans écran
  — un exécuteur d'intégration continue, par exemple — ne peut pas ouvrir de
  fenêtre. Répondre sa version est le seul contrôle qu'on puisse faire là, et
  c'est celui que le workflow de publication exécute.
- **écrire ce qui casse dans un fichier.** Une application graphique Windows
  n'a pas de console : une exception non rattrapée disparaît, et l'utilisateur
  voit une fenêtre qui ne s'ouvre pas, sans rien à envoyer pour comprendre.
- **dire ce qui manque en clair.** ffmpeg absent du PATH est le cas le plus
  probable sur un poste neuf, et « ModuleNotFoundError » ne le dit à personne.

Jamais lancé sur une machine Windows au moment d'écrire ces lignes : ce que le
workflow prouvera, c'est qu'il se construit et qu'il démarre.
"""

from __future__ import annotations

import contextlib
import sys
import traceback
from pathlib import Path


def log() -> Path:
    """Où écrire ce qui casse. `%LOCALAPPDATA%` sur Windows, le dossier des
    données ailleurs — le même endroit que le reste des traces de l'outil."""
    import os

    base = os.environ.get("LOCALAPPDATA")
    folder = Path(base) / "Greffier" if base else Path.home() / ".greffier"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "demarrage.log"


def version() -> str:
    from greffier.adapters.updates import installed_version

    return installed_version() or "inconnue"


def main() -> int:
    if "--version" in sys.argv:
        print(f"Greffier {version()}")
        return 0
    try:
        # Importé ici et non en tête : sur `--version`, charger l'interface
        # coûterait Tk et les modèles pour une chaîne de caractères.
        from greffier.adapters.configuration import Config
        from greffier.interface.window import Window
        from greffier.locations import locate_tcl

        locate_tcl()
        Window(Config()).loop()
    except Exception:  # noqa: BLE001 — dernier recours avant l'écran noir
        trace = traceback.format_exc()
        target = log()
        with contextlib.suppress(OSError):
            target.write_text(trace, encoding="utf-8")
        _dire_a_l_ecran(
            "Greffier n'a pas pu démarrer.\n\n"
            f"Le détail est dans :\n{target}\n\n"
            + _cause_probable(trace)
        )
        return 1
    return 0


def _cause_probable(trace: str) -> str:
    """Ce qui manque, quand la trace le dit clairement.

    Deux cas couvrent presque tout sur un poste neuf, et aucun des deux ne se
    devine à la lecture d'une trace Python.
    """
    if "ffmpeg" in trace.lower():
        return ("ffmpeg est probablement absent. Installez-le, ou lancez "
                "l'installeur de Greffier.")
    if "Tcl" in trace or "tkinter" in trace:
        return "L'interface graphique n'a pas pu s'ouvrir (Tcl/Tk introuvable)."
    return ""


def _dire_a_l_ecran(message: str) -> None:
    """Une boîte de dialogue, ou la sortie d'erreur à défaut.

    À défaut, parce que si Tk est justement ce qui manque, une boîte de dialogue
    Tk ne s'affichera pas — et c'est un cas probable ici.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Greffier", message)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
