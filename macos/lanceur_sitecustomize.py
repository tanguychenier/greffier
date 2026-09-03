"""Fait démarrer Greffier quand macOS lance le paquet .app.

`Contents/MacOS/Greffier` est une copie de l'interpréteur, pas un script :
macOS le lance sans argument. Ce module, posé par `construire.sh` parmi les
paquets embarqués dans l'application (`Contents/lib/python3.x/site-packages`)
et importé automatiquement par le mécanisme « site » au démarrage de
l'interpréteur, joue le rôle que jouait le script shell qui appelait
« python -m greffier fenetre ».

Généré par `construire.sh` à partir de ce fichier : l'espace réservé qui
suit cette docstring est remplacé par le PATH mesuré sur la machine qui
construit le paquet. Le fichier du dépôt n'est donc pas exécutable tel quel —
seule la copie dans le paquet l'est, jamais la ligne de commande.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# `LSEnvironment` (Info.plist) pose PYTHONPATH de façon fiable, mesuré — mais
# pas PATH : macOS semble imposer le sien (`/usr/bin:/bin:/usr/sbin:/sbin`)
# par-dessus, quel que soit ce que dit le paquet. ffmpeg (Homebrew) et claude
# (`~/.local/bin` ou équivalent) en dépendent, et échouaient donc en silence
# jusqu'au clic qui en avait besoin — constaté deux fois avant que la vraie
# cause n'apparaisse. Le fixer ici, en Python, où rien d'autre ne peut plus
# l'écraser.
os.environ["PATH"] = __CHEMIN__ + os.pathsep + os.environ.get("PATH", "")  # noqa: F821

# Tout le code du paquet est compilé à l'avance par `construire.sh`. Un .pyc
# écrit après coup dans l'application en romprait le sceau de signature ;
# Info.plist pose déjà PYTHONDONTWRITEBYTECODE, ceci vaut pour tout appel qui
# n'y passerait pas.
sys.dont_write_bytecode = True

# Ne détourner QUE le double-clic : l'exécutable lancé sans aucun argument
# par LaunchServices. La fenêtre lance elle-même des processus auxiliaires
# avec ce même interpréteur (« -m greffier veiller », « -m greffier
# assister ») : les détourner aussi ouvrait une fenêtre de plus par processus
# — trois « Greffier » à l'écran au démarrage d'une réunion — pendant que la
# vraie veille et le vrai direct ne tournaient jamais, laissant l'onglet
# En direct vide. Constaté en réunion réelle. `sys.orig_argv` porte la ligne
# de commande du processus telle quelle, avant que « -m » ne réécrive
# `sys.argv` ; à cette étape du démarrage, c'est le seul repère fiable.
if len(sys.orig_argv) == 1:
    journal = Path.home() / "Library/Logs/Greffier.log"
    journal.parent.mkdir(parents=True, exist_ok=True)
    flux = journal.open("a", encoding="utf-8")
    sys.stdout = sys.stderr = flux

    sys.argv = ["greffier", "fenetre"]
    from greffier.cli import application

    try:
        application()
    except SystemExit:
        # Normal : Typer en lève un à la fin. Mais un SystemExit qui s'échappe
        # de sitecustomize (module chargé par `site`, pas un script) n'est pas
        # traité comme une sortie propre — mesuré : l'interpréteur l'annonce
        # comme une « Fatal Python error » et quitte en erreur. L'avaler ici.
        pass
    except Exception:
        import traceback

        traceback.print_exc()
    finally:
        # os._exit, pas sys.exit : sans script à lancer ensuite, un retour
        # normal laisserait l'interpréteur tomber sur une invite interactive
        # fantôme, et sys.exit ici lève la même « Fatal Python error ».
        os._exit(0)
