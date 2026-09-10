"""Ce qu'on lit dans un compte rendu sans savoir comment il sera transporté.

Le titre d'un compte rendu est une donnée du document, pas une décision de
courriel. Il vivait dans le gabarit HTML, ce qui obligeait la chaîne de
traitement et la fenêtre à importer un adaptateur d'envoi pour connaître le nom
d'une réunion.
"""

from __future__ import annotations

import re

_GRAS = re.compile(r"\*\*(.+?)\*\*")

def title(minutes: str, defaut: str) -> str:
    """Sujet du courriel : le titre du compte rendu, pas le nom du fichier.

    « Compte rendu de réunion — 2026-08-25_14h33_reunion-essai-reel » n'aide
    personne à retrouver un message six mois plus tard.
    """
    for line in minutes.splitlines():
        nue = line.strip()
        if nue.startswith("# "):
            title = _GRAS.sub(r"\1", nue[2:].strip())
            return title or defaut
        if nue:
            break
    return defaut
