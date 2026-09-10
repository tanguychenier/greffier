"""La banque de voix : un fichier par personne, sur le disque.

C'est ce qui fait qu'une réunion sur deux n'a plus besoin d'être annotée. Une
fois qu'une voix porte un nom, elle est reconnue les fois suivantes.

Format volontairement lisible — du JSON, un fichier par personne — plutôt qu'une
base de données : on doit pouvoir supprimer quelqu'un de la banque en effaçant
un fichier, sans outil ni requête. Pour des données biométriques, savoir
exactement où elles sont et pouvoir les détruire d'un geste n'est pas un détail.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.models import Person, Voiceprint
from greffier.domain.texts import short_voiceprint
from greffier.domain.voiceprints import EMPREINTES_PAR_PERSONNE, enrichir

FORMAT = 1

def _file_at(name: str) -> str:
    """Nom de fichier sûr, dérivé du nom de la personne.

    Sans accents ni espaces : les systèmes de fichiers ne les normalisent pas
    tous de la même façon, et « Josiane » retrouvée sous deux orthographes
    créerait deux personnes.

    Quand la réduction ne laisse rien — un nom cyrillique, grec, arabe ou
    idéographique n'a aucune lettre ASCII — c'est l'écueil inverse qui guettait :
    « sans-nom » pour tout le monde faisait de deux personnes une seule, dans le
    fichier même qui doit les tenir séparées.
    """
    depouille = unicodedata.normalize("NFD", name)
    without_accents = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    reduit = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-").lower()
    return reduit or short_voiceprint(name)

class BanqueFichiers:
    def __init__(self, folder: Path, maximum: int = EMPREINTES_PAR_PERSONNE) -> None:
        self.folder = folder
        self.maximum = maximum

    def people(self) -> list[Person]:
        if not self.folder.exists():
            return []
        connues = []
        for file in sorted(self.folder.glob("*.json")):
            personne = self._read(file)
            if personne is not None:
                connues.append(personne)
        return connues

    def _read(self, file: Path) -> Person | None:
        try:
            content = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if content.get("format", 0) > FORMAT:
            return None
        return Person(
            name=content["nom"],
            voiceprints=[
                Voiceprint(vector=tuple(e["vecteur"]), source_duration=e.get("duree", 0.0),
                          origine=e.get("origine", ""))
                for e in content.get("empreintes", [])
            ],
            vu_le=(
                datetime.fromisoformat(content["vu_le"]) if content.get("vu_le") else None
            ),
            meetings=content.get("reunions", 0),
        )

    def find(self, name: str) -> Person | None:
        file = self.folder / f"{_file_at(name)}.json"
        return self._read(file) if file.exists() else None

    def forget_a_meeting(self, identifier: str) -> dict[str, int]:
        """Retire de toute la banque les empreintes venues d'une réunion.

        Le geste qui manquait. Une réunion mal attribuée verse des empreintes
        fausses sous plusieurs noms d'un coup, et il fallait ensuite les
        retrouver une par une, à la durée, en devinant. Ici on nomme la réunion
        fautive et la banque revient à ce qu'elle était avant.
        """
        retires: dict[str, int] = {}
        for personne in self.people():
            rangs = [
                rank for rank, voiceprint in enumerate(personne.voiceprints)
                if voiceprint.origine == identifier
            ]
            if rangs:
                retires[personne.name] = self.remove_voiceprints(personne.name, rangs)
        return retires

    def record(self, name: str, voiceprint: Voiceprint) -> Person:
        """Ajoute une empreinte à quelqu'un, en le créant au besoin."""
        personne = self.find(name) or Person(name=name)
        enrichir(personne, voiceprint, maximum=self.maximum)
        personne.vu_le = datetime.now(UTC)
        self._write(personne)
        return personne

    def _write(self, personne: Person) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{_file_at(personne.name)}.json"
        content = {
            "format": FORMAT,
            "nom": personne.name,
            "vu_le": personne.vu_le.isoformat() if personne.vu_le else None,
            "reunions": personne.meetings,
            "empreintes": [
                {"vecteur": list(e.vector), "duree": e.source_duration,
                 "origine": e.origine}
                for e in personne.voiceprints
            ],
        }
        temporary = path.with_suffix(".json.partiel")
        temporary.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return path

    def rename(self, former: str, nouveau: str) -> Person:
        """Corrige un nom mal saisi, sans perdre les empreintes accumulées."""
        personne = self.find(former)
        if personne is None:
            raise KeyError(f"« {former} » n'est pas dans la banque de voix.")
        (self.folder / f"{_file_at(former)}.json").unlink()
        personne.name = nouveau
        self._write(personne)
        return personne

    def join(self, garde: str, absorbe: str) -> Person:
        """Réunit deux entrées qui désignaient la même personne."""
        principal = self.find(garde)
        secondaire = self.find(absorbe)
        if principal is None or secondaire is None:
            raise KeyError("les deux personnes doivent exister dans la banque")
        for voiceprint in secondaire.voiceprints:
            enrichir(principal, voiceprint, maximum=self.maximum)
        principal.meetings = max(principal.meetings, secondaire.meetings)
        (self.folder / f"{_file_at(absorbe)}.json").unlink()
        self._write(principal)
        return principal

    def remove_voiceprints(self, name: str, rangs: list[int]) -> int:
        """Enlève des empreintes précises, sans effacer la personne.

        Effacer quelqu'un pour une seule empreinte fautive perd tout le reste,
        y compris les empreintes justes accumulées sur plusieurs réunions. Ce
        qui décide de la reconnaissance, c'est l'empreinte, pas la personne :
        c'est donc à ce grain qu'on doit pouvoir corriger.

        La personne disparaît si l'on retire tout : une entrée sans empreinte
        ne reconnaîtrait plus rien et resterait à traîner dans la liste.
        """
        personne = self.find(name)
        if personne is None:
            return 0
        a_retirer = {r for r in rangs if 0 <= r < len(personne.voiceprints)}
        if not a_retirer:
            return 0
        personne.voiceprints = [
            e for i, e in enumerate(personne.voiceprints) if i not in a_retirer
        ]
        if not personne.voiceprints:
            self.forget(name)
            return len(a_retirer)
        self._write(personne)
        return len(a_retirer)

    def forget(self, name: str) -> bool:
        """Efface une personne. Une empreinte vocale est une donnée biométrique :
        il doit être possible de la supprimer, simplement et complètement."""
        file = self.folder / f"{_file_at(name)}.json"
        if not file.exists():
            return False
        file.unlink()
        return True
