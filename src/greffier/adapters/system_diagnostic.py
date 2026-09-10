"""Ce que la machine sait faire, et ce qui lui manque.

Aucune question posée, aucune décision prise : ce module ne fait que constater.
L'assistant de configuration s'en sert pour proposer des réponses par défaut qui
tiennent debout, et « greffier diagnostic » l'affiche tel quel.

Séparer le constat de la décision permet de tester les deux : on peut vérifier
qu'un poste sans micro reçoit le bon conseil sans avoir à débrancher un micro.
"""

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
    Constat,
    Diagnostic,
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
    """Si la session a un serveur de son auquel se brancher.

    « pactl » n'enregistre rien : il interroge le serveur, là où ffmpeg s'y
    branche directement par sa prise. Juger la capture sur cet outil déclarait
    donc perdue une machine parfaitement capable d'enregistrer — PipeWire en
    marche, mais « pulseaudio-utils » jamais installé.
    """
    if os.environ.get("PULSE_SERVER"):
        return True
    execution = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return (Path(execution) / "pulse" / "native").exists()

def speedup() -> str:
    """Le calcul disponible pour la transcription."""
    if SYSTEM == "Darwin" and platform.machine() == "arm64":
        return "metal"
    if shutil.which("nvidia-smi"):
        return "cuda"
    return "processeur"

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
    """Vérifie que la session Claude Code existe.

    Sans authentification, Claude Code est installé mais incapable de rédiger
    quoi que ce soit — et l'erreur n'apparaîtrait qu'après une heure de
    transcription, au pire moment. On regarde le marqueur de session plutôt que
    d'appeler le modèle : la vérification doit être gratuite et instantanée.
    """
    file = Path.home() / ".claude.json"
    if not file.exists():
        return False
    try:
        content = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(content.get("oauthAccount") or content.get("userID"))

@dataclass(frozen=True)
class CompteClaude:
    """Qui rédige, vu du poste. Lu du fichier de session, jamais du réseau."""

    adresse: str
    organisation: str
    formule: str

    def __str__(self) -> str:
        chunks = [m for m in (self.adresse, self.organisation) if m]
        return " · ".join(chunks) if chunks else "session ouverte"

def claude_account() -> CompteClaude | None:
    """Le compte Claude Code connecté, ou None si aucune session.

    On lit le marqueur de session plutôt que d'interroger l'API : la fenêtre
    affiche ce renseignement à chaque ouverture de l'onglet, et un appel réseau
    y ferait une attente là où il n'y a rien à attendre. Aucun jeton n'est lu,
    seulement de quoi reconnaître le compte.
    """
    file = Path.home() / ".claude.json"
    try:
        content = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    count = content.get("oauthAccount") or {}
    if not (count or content.get("userID")):
        return None
    return CompteClaude(
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

def system_capture() -> Constat:
    """De quoi réenregistrer ce que jouent les haut-parleurs.

    C'est ce qui permet d'entendre les autres participants d'une visio. Le seul
    point où les trois systèmes divergent vraiment.
    """
    if SYSTEM == "Darwin":
        output = subprocess.run(["system_profiler", "SPAudioDataType"],
                                capture_output=True, text=True, check=False).stdout
        present = "BlackHole" in output
        return Constat(
            name="Capture du son des autres participants",
            present=present,
            detail="BlackHole installé" if present else "BlackHole absent",
            remede="brew install --cask blackhole-2ch && sudo killall coreaudiod",
        )
    if SYSTEM == "Linux":
        present = sound_server_present()
        return Constat(
            name="Capture du son des autres participants",
            present=present,
            detail="moniteur PipeWire/PulseAudio" if present else "aucun serveur de son",
            remede="installe « pipewire-pulse » ou « pulseaudio »",
        )
    return Constat(
        name="Capture du son des autres participants",
        present=True,
        detail="boucle WASAPI intégrée à Windows",
    )

def mic_present() -> Constat:
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
    return Constat(name="Micro", present=present, detail=detail,
                   remede="branche un micro ou un casque", bloquant=True)

def examine(data_folder: Path | None = None) -> Diagnostic:
    """Tout ce qu'il faut savoir avant de configurer quoi que ce soit."""
    infos = recorder(data_folder)
    constats = [
        Constat(
            name="ffmpeg", present=shutil.which("ffmpeg") is not None,
            detail="enregistrement et conversion audio",
            remede="brew install ffmpeg" if SYSTEM == "Darwin" else "installe ffmpeg",
            bloquant=True,
        ),
        mic_present(),
        system_capture(),
        Constat(
            name="Claude Code", present=claude_installed(),
            detail=claude_version() or "absent",
            remede=COMMANDE_INSTALLER_CLAUDE.get(SYSTEM, ""),
        ),
        Constat(
            name="Session Claude", present=claude_signed_in(),
            detail="authentifiée" if claude_signed_in() else "jamais connectée",
            remede="lance « claude » une fois et connecte-toi",
        ),
        Constat(
            name="Mémoire vive", present=infos.supports_large_model,
            detail=f"{infos.memory_gb:.0f} Go — modèle conseillé : {infos.advised_model}",
            remede="un modèle plus petit sera utilisé, la transcription sera moins fine",
        ),
        Constat(
            name="Espace disque", present=infos.disque_libre_go >= DISQUE_NECESSAIRE_GO,
            detail=(f"{infos.disque_libre_go:.0f} Go libres, "
                    f"{DISQUE_NECESSAIRE_GO:.0f} Go nécessaires"),
            remede="libère de la place avant de télécharger les modèles",
            bloquant=True,
        ),
    ]
    return Diagnostic(recorder=infos, constats=constats)
