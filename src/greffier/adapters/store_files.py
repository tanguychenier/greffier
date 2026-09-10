"""A meeting's master file: everything known about it, in one place."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from greffier.domain.meeting import Join, StoredMeeting, held_on
from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

FORMAT = 2

class FileStore:
    """Files and reads back the master files, one per meeting."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _path(self, identifier: str) -> Path:
        return self.folder / f"{identifier}.json"

    def record(self, meeting: StoredMeeting) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        content = {
            "format": FORMAT,
            "identifiant": meeting.identifier,
            "audio": str(meeting.audio),
            "traitee_le": meeting.traitee_le.isoformat(),
            "sujet": meeting.subject,
            "commencee_le": meeting.commencee_le.isoformat() if meeting.commencee_le else "",
            "terminee_le": meeting.terminee_le.isoformat() if meeting.terminee_le else "",
            "duree": meeting.duration,
            "noms": meeting.names,
            "propositions": meeting.propositions,
            "avertissements": meeting.warnings,
            "evenements_materiel": meeting.hardware_events,
            "couverture": round(meeting.coverage, 4),
            "tours": [
                {"debut": t.span.start, "fin": t.span.end,
                 "voix": t.voice, "source": t.source.value}
                for t in meeting.turns
            ],
            "repliques": [
                {"debut": r.span.start, "fin": r.span.end,
                 "texte": r.text, "voix": r.voice, "source": r.source.value}
                for r in meeting.utterances
            ],
            "fusions": [
                {"absorbee": f.absorbed, "gardee": f.kept,
                 "tours": list(f.turns), "repliques": list(f.utterances),
                 "nom": f.name, "proposition": f.proposition}
                for f in meeting.joins
            ],
        }
        path = self._path(meeting.identifier)
        temporary = path.with_suffix(".json.partiel")
        temporary.write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
        return path

    def read(self, identifier: str) -> StoredMeeting:
        path = self._path(identifier)
        if not path.exists():
            raise FileNotFoundError(
                f"Réunion « {identifier} » inconnue. « greffier reunions » les liste."
            )
        content = json.loads(path.read_text(encoding="utf-8"))
        if content.get("format", 0) > FORMAT:
            raise ValueError(
                f"{path} vient d'une version plus récente de Greffier (format "
                f"{content['format']}, connu jusqu'à {FORMAT})."
            )
        return StoredMeeting(
            identifier=content["identifiant"],
            audio=Path(content["audio"]),
            traitee_le=datetime.fromisoformat(content["traitee_le"]),
            subject=content.get("sujet", ""),
            commencee_le=(
                datetime.fromisoformat(content["commencee_le"])
                if content.get("commencee_le") else None
            ),
            terminee_le=(
                datetime.fromisoformat(content["terminee_le"])
                if content.get("terminee_le") else None
            ),
            duration=content["duree"],
            names=content.get("noms", {}),
            propositions=content.get("propositions", {}),
            warnings=content.get("avertissements", []),
            hardware_events=content.get("evenements_materiel", []),
            joins=[
                Join(
                    absorbed=str(f.get("absorbee", "")),
                    kept=str(f.get("gardee", "")),
                    turns=tuple(int(x) for x in f.get("tours", [])),
                    utterances=tuple(int(x) for x in f.get("repliques", [])),
                    name=f.get("nom") or None,
                    proposition=f.get("proposition") or None,
                )
                for f in content.get("fusions", [])
                if isinstance(f, dict) and f.get("absorbee") and f.get("gardee")
            ],
            turns=[
                SpeakerTurn(Span(t["debut"], t["fin"]), t["voix"],
                             Source(t.get("source", "inconnue")))
                for t in content.get("tours", [])
            ],
            utterances=[
                Utterance(Span(r["debut"], r["fin"]), r["texte"], r.get("voix"),
                         Source(r.get("source", "inconnue")))
                for r in content.get("repliques", [])
            ],
        )

    def lister(self) -> list[str]:
        """The meetings, most recently **held** first."""
        if not self.folder.exists():
            return []

        def recency(file: Path) -> tuple[int, tuple[int, ...], float]:
            tenue = held_on(file.stem)
            if tenue is None:
                return (0, (0, 0, 0, 0, 0), file.stat().st_mtime)
            return (1, tenue, 0.0)

        return [f.stem for f in sorted(self.folder.glob("*.json"),
                                       key=recency, reverse=True)]

    def delete(self, identifier: str) -> bool:
        """Forgets the master file. False when there was none."""
        path = self._path(identifier)
        if not path.exists():
            return False
        path.unlink()
        return True

    def latest(self) -> StoredMeeting | None:
        identifiers = self.lister()
        return self.read(identifiers[0]) if identifiers else None
