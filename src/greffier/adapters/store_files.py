"""Le fichier maître d'une réunion : tout ce qui a été dit, quand, et par qui.

Un seul fichier JSON par réunion, qui devient la source de vérité. Le compte
rendu en découle, mais on peut y revenir des semaines plus tard pour renommer
une voix, réécouter un passage ou refaire la synthèse autrement — sans
retranscrire l'heure d'audio.

Les horodatages sont conservés jusqu'au bout : ce sont eux qui permettent de
vérifier une citation, de découper un extrait, et de dire ce que la
transcription a perdu.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from greffier.domain.meeting import StoredMeeting, held_on
from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

FORMAT = 2

class FileStore:
    """Range et relit les fichiers maîtres, un par réunion."""

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
        """Les réunions, la plus récemment **tenue** d'abord.

        Trié sur l'horodatage que porte l'identifiant, et non par ordre
        alphabétique : « fausse-reunion » passait avant « 2026-09-09_10h05… »
        parce que « f » vient après « 2 », et devenait donc « la dernière
        réunion » pour toutes les commandes appelées sans argument — jusqu'à
        « greffier envoyer », qui expédiait le compte rendu d'une autre réunion
        que celle qui venait de se tenir. Constaté le 2026-09-09.

        Les identifiants sans date vont en fin de liste : ils ne peuvent pas
        prétendre être les derniers. Entre eux, du plus récemment écrit, faute
        de mieux.
        """
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
        """Oublie le fichier maître. Rend False s'il n'y en avait pas.

        Ne touche à rien d'autre : l'audio, la transcription et le compte rendu
        appartiennent à qui sait ce qu'ils valent — voir `application.ranger`,
        qui les rassemble pour qu'on puisse dire ce qu'on efface avant de le
        faire.
        """
        path = self._path(identifier)
        if not path.exists():
            return False
        path.unlink()
        return True

    def latest(self) -> StoredMeeting | None:
        identifiers = self.lister()
        return self.read(identifiers[0]) if identifiers else None
