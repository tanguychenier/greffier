"""Rend Tkinter utilisable avant qu'on l'importe.

Les distributions Python autonomes — celles qu'installent `uv` et `pyenv`, et
celles qu'embarque un paquet figé — livrent `_tkinter` compilé et les fichiers de
bibliothèque Tcl, mais ces derniers ne sont pas là où Tcl les cherche : il tente
le chemin de compilation de la machine qui a construit l'interpréteur.

    Cannot find a usable init.tcl in the following directories:
        /tools/deps/lib/tcl9.0 …

Les fichiers sont pourtant à deux répertoires de là. On les trouve et on renseigne
`TCL_LIBRARY` et `TK_LIBRARY`, qui doivent être posées **avant** le premier import
de `tkinter` : Tcl les lit à son initialisation, et n'y revient jamais.

Rien n'est écrasé : un environnement qui les définit déjà sait mieux que nous.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _racines(prefixe: Path) -> list[Path]:
    """Où chercher, du plus probable au moins."""
    return [prefixe / "lib", prefixe / "share", prefixe]


def _trouver(motif: str, prefixes: list[Path]) -> Path | None:
    for prefixe in prefixes:
        for racine in _racines(prefixe):
            if not racine.is_dir():
                continue
            # Version la plus récente d'abord : « tcl9.0 » avant « tcl8.6 ».
            for dossier in sorted(racine.glob(motif), reverse=True):
                if (dossier / "init.tcl").exists() or motif.startswith("tk"):
                    return dossier
    return None


def preparer() -> dict[str, str]:
    """Renseigne les chemins Tcl/Tk manquants. Rend ce qui a été posé."""
    prefixes = [Path(sys.base_prefix), Path(sys.prefix)]
    pose: dict[str, str] = {}
    for variable, motif in (("TCL_LIBRARY", "tcl[0-9]*"), ("TK_LIBRARY", "tk[0-9]*")):
        if os.environ.get(variable):
            continue
        trouve = _trouver(motif, prefixes)
        if trouve is not None:
            os.environ[variable] = str(trouve)
            pose[variable] = str(trouve)
    return pose


def disponible() -> tuple[bool, str]:
    """Dit si une fenêtre peut s'ouvrir, et pourquoi non le cas échéant.

    **Rien n'est instancié.** Créer une racine Tk pour l'éprouver, la détruire,
    puis en créer une seconde pour la vraie fenêtre fait tomber le processus en
    erreur de segmentation sur macOS avec Tk 9. On se contente donc de vérifier
    que le module se charge et que les fichiers Tcl ont été trouvés.
    """
    pose = preparer()
    try:
        import tkinter
    except ImportError:
        return False, (
            "Tkinter n'est pas installé avec ce Python. "
            "Sur Debian ou Ubuntu : « apt install python3-tk ». "
            "Sur macOS avec Homebrew : « brew install python-tk »."
        )
    if not os.environ.get("TCL_LIBRARY") and not _tcl_par_defaut():
        return False, (
            "les fichiers de bibliothèque Tcl sont introuvables. "
            "Renseigne TCL_LIBRARY, ou installe Tcl/Tk pour ce Python."
        )
    trouve = " (chemins Tcl résolus)" if pose else ""
    return True, f"Tkinter {tkinter.TkVersion}{trouve}"


def _tcl_par_defaut() -> bool:
    """Vrai quand Tcl trouvera ses fichiers sans qu'on l'aide.

    C'est le cas des Python livrés par une distribution ou par Homebrew, où Tcl
    est installé à l'endroit qu'il attend.
    """
    return any(
        (racine / "init.tcl").exists()
        for prefixe in (Path(sys.base_prefix), Path("/usr"), Path("/opt/homebrew"))
        for racine in prefixe.glob("lib/tcl*")
    )
