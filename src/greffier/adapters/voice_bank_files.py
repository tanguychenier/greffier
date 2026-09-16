"""The voice bank: one file per person, on this machine only.

A voiceprint is biometric data. It never leaves the machine, and every gesture
here (forget, rename, remove) exists so that it can be taken back.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.models import Person, Voiceprint
from greffier.domain.texts import short_voiceprint
from greffier.domain.voiceprints import VOICEPRINTS_PER_PERSON, enrich

FORMAT = 1

def _file_at(name: str) -> str:
    """A safe file name, derived from the person's name."""
    stripped = unicodedata.normalize("NFD", name)
    without_accents = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    reduced = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-").lower()
    return reduced or short_voiceprint(name)

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
            ranks = [
                rank for rank, voiceprint in enumerate(person.voiceprints)
                if voiceprint.origin == identifier
            ]
            if ranks:
                retires[person.name] = self.remove_voiceprints(person.name, ranks)
        return retires

    def record(self, name: str, voiceprint: Voiceprint) -> Person:
        """Adds a voiceprint to someone, creating them if needed."""
        person = self.find(name) or Person(name=name)
        enrich(person, voiceprint, maximum=self.maximum)
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

    def join(self, kept: str, absorbed: str) -> Person:
        """Joins two entries that named the same person."""
        principal = self.find(kept)
        secondary = self.find(absorbed)
        if principal is None or secondary is None:
            raise KeyError("les deux personnes doivent exister dans la banque")
        for voiceprint in secondary.voiceprints:
            enrich(principal, voiceprint, maximum=self.maximum)
        principal.meetings = max(principal.meetings, secondary.meetings)
        (self.folder / f"{_file_at(absorbed)}.json").unlink()
        self._write(principal)
        return principal

    def remove_voiceprints(self, name: str, ranks: list[int]) -> int:
        """Removes specific voiceprints, without erasing the person."""
        person = self.find(name)
        if person is None:
            return 0
        to_remove = {r for r in ranks if 0 <= r < len(person.voiceprints)}
        if not to_remove:
            return 0
        person.voiceprints = [
            e for i, e in enumerate(person.voiceprints) if i not in to_remove
        ]
        if not person.voiceprints:
            self.forget(name)
            return len(to_remove)
        self._write(person)
        return len(to_remove)

    def forget(self, name: str) -> bool:
        """Erases a person, voiceprints included."""
        file = self.folder / f"{_file_at(name)}.json"
        if not file.exists():
            return False
        file.unlink()
        return True
