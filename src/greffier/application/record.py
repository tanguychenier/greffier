"""The state machine of a recording.

One state file, read by every process. It survives a crash, which is the whole
reason it exists rather than a variable in memory.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.models import Phase
from greffier.domain.texts import short_voiceprint
from greffier.ports import outbound


def _identifier(name: str, horodatage: datetime) -> str:
    """A readable, sortable file name: the date first."""
    depouille = unicodedata.normalize("NFD", name)
    without_accents = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    reduit = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-").lower()
    return f"{horodatage:%Y-%m-%d_%Hh%M}_{reduit or short_voiceprint(name)}"

def _kill_tree(pid: int) -> None:
    """Stops a process and its descendants."""
    import signal
    import subprocess

    try:
        enfants = subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        enfants = []
    for enfant in enfants:
        _kill_tree(int(enfant))
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.kill(pid, signal.SIGTERM)

def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True

@dataclass
class RecorderState:
    """What the interface needs to know, without computing anything."""

    phase: Phase = Phase.REST
    message: str = ""
    name: str = ""
    identifier: str = ""
    audio: Path | None = None
    start: datetime | None = None
    pid: int | None = None
    chunks: list[Path] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    suspendu_le: datetime | None = None
    pause_totale: float = 0.0
    terminee_le: datetime | None = None
    sortie_precedente: str = ""

    @property
    def seconds(self) -> float:
        """Time actually recorded, pauses deducted."""
        if self.start is None:
            return 0.0
        ecoule = (datetime.now(UTC) - self.start).total_seconds() - self.pause_totale
        if self.suspendu_le is not None:
            ecoule -= (datetime.now(UTC) - self.suspendu_le).total_seconds()
        return max(0.0, ecoule)

@dataclass
class StateLog:
    """Publishes progress, but only for the meeting the state carries."""

    state: Recording
    identifier: str

    def publish(self, phase: str, message: str = "") -> None:
        try:
            current = self.state.read()
        except (OSError, ValueError):
            return
        if current.identifier and current.identifier != self.identifier:
            return
        self.state.publish(phase, message)

class Recording:
    """Starts, stops, and can say where things stand."""

    def __init__(
        self,
        audio_recorder: outbound.AudioRecorder,
        dossier_audio: Path,
        fichier_etat: Path,
    ) -> None:
        self.audio_recorder = audio_recorder
        self.dossier_audio = dossier_audio
        self.fichier_etat = fichier_etat

    def read(self) -> RecorderState:
        if not self.fichier_etat.exists():
            return RecorderState()
        try:
            content = json.loads(self.fichier_etat.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return RecorderState()
        state = RecorderState(
            phase=Phase(content.get("phase", Phase.REST.value)),
            message=content.get("message", ""),
            name=content.get("nom", ""),
            identifier=content.get("identifiant", ""),
            audio=Path(content["audio"]) if content.get("audio") else None,
            start=datetime.fromisoformat(content["debut"]) if content.get("debut") else None,
            pid=content.get("pid"),
            chunks=[Path(x) for x in content.get("morceaux", [])],
            events=list(content.get("evenements", [])),
            suspendu_le=(
                datetime.fromisoformat(content["suspendu_le"])
                if content.get("suspendu_le") else None
            ),
            pause_totale=float(content.get("pause_totale", 0.0)),
            terminee_le=(
                datetime.fromisoformat(content["terminee_le"])
                if content.get("terminee_le") else None
            ),
            sortie_precedente=content.get("sortie_precedente", ""),
        )
        if state.phase.in_progress and not _alive(state.pid):
            enregistrait = state.phase in (Phase.RECORDING, Phase.PAUSE)
            state.phase = Phase.ECHEC
            state.message = (
                "Enregistrement interrompu (redémarrage ?). L'audio est conservé."
                if enregistrait
                else "Traitement interrompu (fermeture, veille ?). La "
                     "transcription est gardée : « Rédiger » reprend."
            )
        return state

    def write(self, state: RecorderState) -> None:
        self.fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "phase": state.phase.value,
            "message": state.message,
            "nom": state.name,
            "identifiant": state.identifier,
            "audio": str(state.audio) if state.audio else "",
            "debut": state.start.isoformat() if state.start else "",
            "pid": state.pid,
            "morceaux": [str(x) for x in state.chunks],
            "evenements": state.events,
            "suspendu_le": state.suspendu_le.isoformat() if state.suspendu_le else "",
            "pause_totale": state.pause_totale,
            "terminee_le": state.terminee_le.isoformat() if state.terminee_le else "",
            "sortie_precedente": state.sortie_precedente,
        }
        temporary = self.fichier_etat.with_suffix(".json.partiel")
        temporary.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.fichier_etat)

    def publish(self, phase: str, message: str = "") -> None:
        """Serves as StateJournal: the processing chain publishes its phases here."""
        state = self.read()
        state.phase = Phase(phase)
        state.message = message
        state.pid = os.getpid()
        self.write(state)

    def pour(self, identifier: str) -> StateLog:
        """A log that writes **only** if the state carries this meeting.

        Without that, a processing run started during a recording published its own
        phases through to "done", the window concluded the meeting was over, and
        capture stopped. A whole meeting was lost that way.
        """
        return StateLog(self, identifier)

    def abandon(self) -> RecorderState:
        """Stops the processing under way. The audio is kept."""
        state = self.read()
        pid = state.pid
        if not state.phase.in_progress or not _alive(pid) or pid is None:
            raise RuntimeError("Aucun traitement en cours.")
        _kill_tree(pid)
        state.phase = Phase.INTERROMPU
        state.message = "Traitement interrompu. L'audio est conservé."
        state.pid = None
        self.write(state)
        return state

    def pause(self) -> RecorderState:
        """Suspends the recording without closing the meeting."""
        state = self.read()
        if state.phase is not Phase.RECORDING:
            raise RuntimeError("Aucun enregistrement en cours.")
        if state.pid is not None and _alive(state.pid):
            self.audio_recorder.stop_recording(state.pid)
        state.phase = Phase.PAUSE
        state.pid = None
        state.message = "En pause. Ce qui a été capté est conservé."
        state.suspendu_le = datetime.now(UTC)
        self.write(state)
        return state

    def resume(self) -> RecorderState:
        """Starts again after a pause, on one more chunk."""
        state = self.read()
        if state.phase is not Phase.PAUSE:
            raise RuntimeError("L'enregistrement n'est pas en pause.")
        suivant = self.dossier_audio / f"{state.identifier}-{len(state.chunks) + 1:02d}.wav"
        state.pid = self.audio_recorder.start_recording(suivant)
        state.chunks.append(suivant)
        state.phase = Phase.RECORDING
        state.message = "Enregistrement en cours."
        if state.suspendu_le is not None:
            state.pause_totale += (datetime.now(UTC) - state.suspendu_le).total_seconds()
            state.suspendu_le = None
        self.write(state)
        return state

    def reprendre(self, because: str) -> RecorderState:
        """Closes the current chunk and starts the next."""
        state = self.read()
        if state.phase is not Phase.RECORDING or state.audio is None:
            raise RuntimeError("Aucun enregistrement en cours.")
        if state.pid is not None and _alive(state.pid):
            self.audio_recorder.stop_recording(state.pid)
        suivant = self.dossier_audio / f"{state.identifier}-{len(state.chunks) + 1:02d}.wav"
        state.pid = self.audio_recorder.start_recording(suivant)
        state.chunks.append(suivant)
        state.events.append(because)
        state.message = because
        self.write(state)
        return state

    def report(self, warning: str) -> RecorderState:
        """Notes an observation about the hardware without touching capture."""
        state = self.read()
        state.events.append(warning)
        state.message = warning
        self.write(state)
        return state

    def start_recording(self, name: str = "reunion", sortie_precedente: str = "") -> RecorderState:
        in_progress = self.read()
        if in_progress.phase is Phase.RECORDING:
            raise RuntimeError(
                f"Un enregistrement est déjà en cours depuis "
                f"{in_progress.seconds / 60:.0f} min. « greffier arreter » d'abord."
            )
        horodatage = datetime.now(UTC).astimezone()
        identifier = _identifier(name, horodatage)
        audio = self.dossier_audio / f"{identifier}.wav"
        premier = self.dossier_audio / f"{identifier}-01.wav"
        pid = self.audio_recorder.start_recording(premier)
        state = RecorderState(
            phase=Phase.RECORDING, name=name, identifier=identifier,
            audio=audio, start=datetime.now(UTC), pid=pid,
            chunks=[premier],
            sortie_precedente=sortie_precedente,
            message="Enregistrement en cours.",
        )
        self.write(state)
        return state

    def stop_recording(self) -> RecorderState:
        state = self.read()
        if state.audio is None:
            raise RuntimeError("Aucun enregistrement à arrêter.")
        if state.pid is not None and _alive(state.pid):
            self.audio_recorder.stop_recording(state.pid)
        state.phase = Phase.FINALISATION
        state.message = "Enregistrement arrêté."
        state.pid = None
        state.terminee_le = datetime.now(UTC)
        self.write(state)
        chunks = [m for m in (state.chunks or [state.audio]) if m is not None]
        utiles = [m for m in chunks if m.exists() and m.stat().st_size > 0]
        if not utiles:
            raise RuntimeError(
                f"{state.audio} est vide. Vérifie l'autorisation micro et le "
                "périphérique d'entrée."
            )
        if len(utiles) > 1:
            state.message = f"Enregistrement arrêté, {len(utiles)} morceaux recollés."
        self.audio_recorder.wire_up(utiles, state.audio)
        for morceau in chunks:
            if morceau != state.audio:
                morceau.unlink(missing_ok=True)
        state.chunks = [state.audio]
        self.write(state)
        return state
