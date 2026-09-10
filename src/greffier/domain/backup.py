"""What a backup carries, and how many are kept."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CONTENT = (
    "banque-de-voix",
    "reunions",
    "comptes-rendus",
    "transcriptions",
    "conversations",
    "questions",
    "direct",
    "propositions",
)

ECARTES = {
    "enregistrements": "l'audio, 115 Mo par heure — c'est lui qui rend une "
                       "sauvegarde impossible, et une réunion transcrite reste "
                       "utilisable sans lui",
    "modeles": "2 Go de modèles, retéléchargeables par l'installeur",
    "corpus": "un corpus public, retéléchargeable",
    "extraits": "des extraits recalculables depuis l'audio",
    "sauvegardes": "les sauvegardes elles-mêmes",
    "lectures": "des lectures à voix haute, refabricables",
}

KEPT = 7

@dataclass(frozen=True, slots=True)
class BackupName:
    """A backup's name: its date, down to the minute."""

    quand: datetime

    def __str__(self) -> str:
        return f"greffier-{self.quand:%Y-%m-%d_%Hh%M}"

    @staticmethod
    def read(name: str) -> datetime | None:
        """The date of a backup from its name, or None if it is not one."""
        if not name.startswith("greffier-"):
            return None
        try:
            return datetime.strptime(name[len("greffier-"):], "%Y-%m-%d_%Hh%M")
        except ValueError:
            return None

def to_erase(names: list[str], kept: int = KEPT) -> list[str]:
    """The backups in excess, oldest first."""
    datees = [(BackupName.read(name), name) for name in names]
    connues = sorted(
        ((quand, name) for quand, name in datees if quand is not None),
        reverse=True,
    )
    if len(connues) <= max(1, kept):
        return []
    return [name for _, name in connues[max(1, kept):]]
