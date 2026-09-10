"""The voice bank: one file per person, on this machine only.

A voiceprint is biometric data. It never leaves the machine, and every gesture
here — forget, rename, remove — exists so that it can be taken back.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.models import Person, Voiceprint
from greffier.domain.texts import short_voiceprint
from greffier.domain.voiceprints import VOICEPRINTS_PER_PERSON, enrichir

FORMAT = 1

def _file_at(name: str) -> str:
    """A safe file name, derived from the person's name."""
    depouille = unicodedata.normalize("NFD", name)
    without_accents = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    reduit = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-").lower()
    return reduit or short_voiceprint(name)

class FileVoiceBank:
    def __init__(self, folder: Path, maximum: int = VOICEPRINTS_PER_PERSON) -> None:
        self.folder = folder
        self.maximum = maximum

    def people(self) -> list[Person]:
        if not self.folder.exists():
            return []
        known = []
        for file in sorted(self.folder.glob("*.json")):
            person = self._read(file)
            if person is not None:
                known.append(person)
        return known

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
                          origin=e.get("origine", ""))
                for e in content.get("empreintes", [])
            ],
            seen_at=(
                datetime.fromisoformat(content["vu_le"]) if content.get("vu_le") else None
            ),
            meetings=content.get("reunions", 0),
        )

    def find(self, name: str) -> Person | None:
        file = self.folder / f"{_file_at(name)}.json"
        return self._read(file) if file.exists() else None

    def forget_a_meeting(self, identifier: str) -> dict[str, int]:
        """Removes from the whole bank the voiceprints from one meeting."""
        retires: dict[str, int] = {}
        for person in self.people():
            rangs = [
                rank for rank, voiceprint in enumerate(person.voiceprints)
                if voiceprint.origin == identifier
            ]
            if rangs:
                retires[person.name] = self.remove_voiceprints(person.name, rangs)
        return retires

    def record(self, name: str, voiceprint: Voiceprint) -> Person:
        """Adds a voiceprint to someone, creating them if needed."""
        person = self.find(name) or Person(name=name)
        enrichir(person, voiceprint, maximum=self.maximum)
        person.seen_at = datetime.now(UTC)
        self._write(person)
        return person

    def _write(self, person: Person) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{_file_at(person.name)}.json"
        content = {
            "format": FORMAT,
            "nom": person.name,
            "vu_le": person.seen_at.isoformat() if person.seen_at else None,
            "reunions": person.meetings,
            "empreintes": [
                {"vecteur": list(e.vector), "duree": e.source_duration,
                 "origine": e.origin}
                for e in person.voiceprints
            ],
        }
        temporary = path.with_suffix(".json.partiel")
        temporary.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return path

    def rename(self, former: str, fresh: str) -> Person:
        """Fixes a mistyped name, without losing the voiceprints."""
        person = self.find(former)
        if person is None:
            raise KeyError(f"« {former} » n'est pas dans la banque de voix.")
        (self.folder / f"{_file_at(former)}.json").unlink()
        person.name = fresh
        self._write(person)
        return person

    def join(self, garde: str, absorbe: str) -> Person:
        """Joins two entries that named the same person."""
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
        """Removes specific voiceprints, without erasing the person."""
        person = self.find(name)
        if person is None:
            return 0
        a_retirer = {r for r in rangs if 0 <= r < len(person.voiceprints)}
        if not a_retirer:
            return 0
        person.voiceprints = [
            e for i, e in enumerate(person.voiceprints) if i not in a_retirer
        ]
        if not person.voiceprints:
            self.forget(name)
            return len(a_retirer)
        self._write(person)
        return len(a_retirer)

    def forget(self, name: str) -> bool:
        """Erases a person, voiceprints included."""
        file = self.folder / f"{_file_at(name)}.json"
        if not file.exists():
            return False
        file.unlink()
        return True
