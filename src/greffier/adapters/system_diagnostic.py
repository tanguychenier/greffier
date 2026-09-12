"""What the machine can do, and what it is missing."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from greffier.domain.recorder import (
    DISQUE_NECESSAIRE_GO,
    Diagnostic,
    Reading,
    Recorder,
)

SYSTEM = platform.system()

def memory_gb() -> float:
    try:
        if SYSTEM == "Darwin":
            bytes_read = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                    capture_output=True, text=True, check=False).stdout
            return int(bytes_read.strip()) / 1024**3
        if SYSTEM == "Linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024**2
        if SYSTEM == "Windows":
            output = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                capture_output=True, text=True, check=False).stdout
            chiffres = [m for m in output.split() if m.isdigit()]
            if chiffres:
                return int(chiffres[0]) / 1024**3
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0.0

def sound_server_present() -> bool:
    """Whether the session has a sound server to hook into."""
    if os.environ.get("PULSE_SERVER"):
        return True
    execution = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return (Path(execution) / "pulse" / "native").exists()

def speedup() -> str:
    """The compute available for transcription.

    The driver is asked rather than the presence of `nvidia-smi`: a machine can
    carry the tool without a usable card, and a container the card without the
    tool.
    """
    if SYSTEM == "Darwin" and platform.machine() == "arm64":
        return "metal"
    from greffier.adapters import cuda

    return "cuda" if cuda.a_card_answers() else "processeur"

def recorder(data_folder: Path | None = None) -> Recorder:
    target = data_folder or Path.home()
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        libre = shutil.disk_usage(target).free / 1024**3
    except OSError:
        libre = 0.0
    return Recorder(
        system=SYSTEM,
        architecture=platform.machine(),
        memory_gb=round(memory_gb(), 1),
        disque_libre_go=round(libre, 1),
        speedup=speedup(),
    )

def claude_installed() -> bool:
    return shutil.which("claude") is not None

def claude_version() -> str:
    if not claude_installed():
        return ""
    output = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                            check=False, timeout=20).stdout
    return output.strip().split()[0] if output.strip() else ""

def claude_signed_in() -> bool:
    """Checks that the Claude Code session exists."""
    file = Path.home() / ".claude.json"
    if not file.exists():
        return False
    try:
        content = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(content.get("oauthAccount") or content.get("userID"))

@dataclass(frozen=True)
class ClaudeAccount:
    """Who writes, as seen from the machine."""

    adresse: str
    organisation: str
    formule: str

    def __str__(self) -> str:
        chunks = [m for m in (self.adresse, self.organisation) if m]
        return " · ".join(chunks) if chunks else "session ouverte"

def claude_account() -> ClaudeAccount | None:
    """The signed-in Claude Code account, or None."""
    file = Path.home() / ".claude.json"
    try:
        content = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    count = content.get("oauthAccount") or {}
    if not (count or content.get("userID")):
        return None
    return ClaudeAccount(
        adresse=str(count.get("emailAddress") or ""),
        organisation=str(count.get("organizationName") or ""),
        formule=str(count.get("seatTier") or count.get("billingType") or ""),
    )

COMMANDE_INSTALLER_CLAUDE = {
    "Darwin": "curl -fsSL https://claude.ai/install.sh | bash",
    "Linux": "curl -fsSL https://claude.ai/install.sh | bash",
    "Windows": "irm https://claude.ai/install.ps1 | iex",
}

def outlook_present() -> bool:
    if SYSTEM != "Darwin":
        return False
    return Path("/Applications/Microsoft Outlook.app").exists()

def system_capture() -> Reading:
    """What it takes to record back what the speakers play."""
    if SYSTEM == "Darwin":
        output = subprocess.run(["system_profiler", "SPAudioDataType"],
                                capture_output=True, text=True, check=False).stdout
        present = "BlackHole" in output
        return Reading(
            name="Capture du son des autres participants",
            present=present,
            detail="BlackHole installé" if present else "BlackHole absent",
            remede="brew install --cask blackhole-2ch && sudo killall coreaudiod",
        )
    if SYSTEM == "Linux":
        present = sound_server_present()
        return Reading(
            name="Capture du son des autres participants",
            present=present,
            detail="moniteur PipeWire/PulseAudio" if present else "aucun serveur de son",
            remede="installe « pipewire-pulse » ou « pulseaudio »",
        )
    return Reading(
        name="Capture du son des autres participants",
        present=True,
        detail="boucle WASAPI intégrée à Windows",
    )

def mic_present() -> Reading:
    detail = ""
    present = False
    if SYSTEM == "Darwin":
        output = subprocess.run(["system_profiler", "SPAudioDataType"],
                                capture_output=True, text=True, check=False).stdout
        present = "Input" in output or "Micro" in output
        detail = "au moins une entrée audio détectée" if present else "aucune entrée audio"
    elif SYSTEM == "Linux":
        present = Path("/proc/asound/cards").exists() or sound_server_present()
        detail = "carte son détectée" if present else "aucune carte son"
    else:
        present = True
        detail = "supposé présent"
    return Reading(name="Micro", present=present, detail=detail,
                   remede="branche un micro ou un casque", bloquant=True)

def models_present(data_folder: Path | None = None) -> Reading:
    """The models the chain loads, which no meeting starts without."""
    from greffier.adapters.model_files import missing, weight
    from greffier.locations import data_folder as ou

    folder = (data_folder or ou()) / "modeles"
    engine = "whisper.cpp" if SYSTEM == "Darwin" else "faster-whisper"
    manquants = missing(folder, engine)
    if not manquants:
        return Reading(name="Modèles", present=True,
                       detail="transcription, voix et diarisation en place")
    noms = ", ".join(m.role for m in manquants)
    return Reading(
        name="Modèles", present=False,
        detail=f"{len(manquants)} manquant(s) : {noms}, {weight(manquants)} à télécharger",
        remede="python3 tools/install.py",
        bloquant=any(m.required for m in manquants),
    )

def known_voices(data_folder: Path | None = None) -> Reading:
    """How many people the bank already recognises without being told."""
    from greffier.adapters.voice_bank_files import FileVoiceBank
    from greffier.locations import data_folder as ou

    folder = (data_folder or ou()) / "banque-de-voix"
    if not folder.exists():
        return Reading(name="Banque de voix", present=True,
                       detail="vide : les voix se nomment en réunion")
    try:
        connus = FileVoiceBank(folder).people()
    except (OSError, ValueError) as trouble:
        return Reading(name="Banque de voix", present=False, detail=str(trouble),
                       remede="vérifie les droits sur le dossier banque-de-voix")
    if not connus:
        return Reading(name="Banque de voix", present=True,
                       detail="vide : les voix se nomment en réunion")
    return Reading(name="Banque de voix", present=True,
                   detail=f"{len(connus)} personne(s) reconnue(s) sans rien dire")

def examine(data_folder: Path | None = None) -> Diagnostic:
    """Everything worth knowing before configuring the tool."""
    infos = recorder(data_folder)
    constats = [
        Reading(
            name="ffmpeg", present=shutil.which("ffmpeg") is not None,
            detail="enregistrement et conversion audio",
            remede="brew install ffmpeg" if SYSTEM == "Darwin" else "installe ffmpeg",
            bloquant=True,
        ),
        mic_present(),
        system_capture(),
        Reading(
            name="Claude Code", present=claude_installed(),
            detail=claude_version() or "absent",
            remede=COMMANDE_INSTALLER_CLAUDE.get(SYSTEM, ""),
        ),
        Reading(
            name="Session Claude", present=claude_signed_in(),
            detail="authentifiée" if claude_signed_in() else "jamais connectée",
            remede="lance « claude » une fois et connecte-toi",
        ),
        Reading(
            name="Mémoire vive", present=infos.supports_large_model,
            detail=f"{infos.memory_gb:.0f} Go, modèle conseillé : {infos.advised_model}",
            remede="un modèle plus petit sera utilisé, la transcription sera moins fine",
        ),
        Reading(
            name="Espace disque", present=infos.disque_libre_go >= DISQUE_NECESSAIRE_GO,
            detail=(f"{infos.disque_libre_go:.0f} Go libres, "
                    f"{DISQUE_NECESSAIRE_GO:.0f} Go nécessaires"),
            remede="libère de la place avant de télécharger les modèles",
            bloquant=True,
        ),
        models_present(data_folder),
        known_voices(data_folder),
    ]
    return Diagnostic(recorder=infos, constats=constats)
