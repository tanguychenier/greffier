"""La conversation, gardée sur le disque, réunion par réunion.

Elle ne l'était pas : le fil vivait dans le widget de la fenêtre et disparaissait
à la fermeture. On y pose des questions pendant une réunion, on y reçoit des
liens, des pistes à vérifier, des réponses qu'on voudrait relire le lendemain —
et tout partait au premier redémarrage, mise à jour ou non.

Un fichier par réunion, en ajout seul, comme le fil du direct et la file des
questions. Une conversation ne se réécrit jamais : on ajoute ce qui vient d'être
dit, et relire c'est rejouer le fichier.

Ce que ce module **ne** garde pas : les notes de l'interface adressées à
quelqu'un qui n'a pas encore choisi de réunion. Elles n'appartiennent à aucune
conversation, et les ranger sous une réunion au hasard rendrait le fichier
trompeur.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TOURS_RELUS = 60

@dataclass(frozen=True, slots=True)
class Exchange:
    """Une réplique de la conversation, telle qu'elle a été dite."""

    qui: str
    text: str
    quand: datetime | None = None

def file_for(folder: Path, identifier: str) -> Path:
    return folder / f"{identifier}.jsonl"

def add(file: Path, qui: str, text: str) -> None:
    """Ajoute un tour. N'échoue jamais bruyamment.

    Une conversation qu'on n'arrive pas à écrire ne doit pas empêcher de
    converser : c'est un confort, pas la chaîne de traitement.
    """
    if not text.strip():
        return
    with contextlib.suppress(OSError):
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as flux:
            flux.write(json.dumps(
                {"qui": qui, "texte": text,
                 "quand": datetime.now(UTC).isoformat()},
                ensure_ascii=False,
            ) + "\n")

def read(file: Path, derniers: int = TOURS_RELUS) -> list[Exchange]:
    """Les derniers tours de la conversation, du plus ancien au plus récent."""
    if not file.exists():
        return []
    turns: list[Exchange] = []
    with contextlib.suppress(OSError):
        for brute in file.read_text(encoding="utf-8").splitlines():
            if not brute.strip():
                continue
            try:
                line = json.loads(brute)
            except json.JSONDecodeError:
                continue
            if not isinstance(line, dict) or not str(line.get("texte", "")).strip():
                continue
            quand = None
            with contextlib.suppress(ValueError, TypeError):
                quand = datetime.fromisoformat(str(line.get("quand", "")))
            turns.append(Exchange(
                qui=str(line.get("qui", "note")),
                text=str(line["texte"]),
                quand=quand,
            ))
    return turns[-derniers:] if derniers > 0 else turns
