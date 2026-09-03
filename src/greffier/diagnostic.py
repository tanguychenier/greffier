"""Ce que la machine sait faire, et ce qui lui manque.

Aucune question posée, aucune décision prise : ce module ne fait que constater.
L'assistant de configuration s'en sert pour proposer des réponses par défaut qui
tiennent debout, et « greffier diagnostic » l'affiche tel quel.

Séparer le constat de la décision permet de tester les deux : on peut vérifier
qu'un poste sans micro reçoit le bon conseil sans avoir à débrancher un micro.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SYSTEME = platform.system()

# En dessous, faire tourner le grand modèle de transcription revient à faire
# ramer la machine pendant toute la réunion.
MEMOIRE_GRAND_MODELE_GO = 8.0
# Modèles, VAD, empreintes, segmentation : 1,7 Go, plus la marge d'extraction.
DISQUE_NECESSAIRE_GO = 3.0


@dataclass
class Constat:
    """Un point vérifié, et quoi faire s'il manque."""

    nom: str
    present: bool
    detail: str = ""
    remede: str = ""
    bloquant: bool = False


@dataclass
class Machine:
    systeme: str = SYSTEME
    architecture: str = platform.machine()
    memoire_go: float = 0.0
    disque_libre_go: float = 0.0
    acceleration: str = "processeur"   # metal | cuda | processeur

    @property
    def supporte_grand_modele(self) -> bool:
        return self.memoire_go >= MEMOIRE_GRAND_MODELE_GO

    @property
    def modele_conseille(self) -> str:
        """Le meilleur modèle que cette machine fasse tourner sans souffrir."""
        if self.supporte_grand_modele:
            return "large-v3-turbo" if self.systeme == "Darwin" else "large-v3"
        if self.memoire_go >= 4:
            return "medium"
        return "small"


def memoire_go() -> float:
    try:
        if SYSTEME == "Darwin":
            octets = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                    capture_output=True, text=True, check=False).stdout
            return int(octets.strip()) / 1024**3
        if SYSTEME == "Linux":
            for ligne in Path("/proc/meminfo").read_text().splitlines():
                if ligne.startswith("MemTotal:"):
                    return int(ligne.split()[1]) / 1024**2
        if SYSTEME == "Windows":
            sortie = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                capture_output=True, text=True, check=False).stdout
            chiffres = [m for m in sortie.split() if m.isdigit()]
            if chiffres:
                return int(chiffres[0]) / 1024**3
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0.0


def acceleration() -> str:
    """Le calcul disponible pour la transcription."""
    if SYSTEME == "Darwin" and platform.machine() == "arm64":
        # Toute puce Apple Silicon expose Metal : whisper.cpp s'en sert seul.
        return "metal"
    if shutil.which("nvidia-smi"):
        return "cuda"
    return "processeur"


def machine(dossier_donnees: Path | None = None) -> Machine:
    cible = dossier_donnees or Path.home()
    while not cible.exists() and cible.parent != cible:
        cible = cible.parent
    try:
        libre = shutil.disk_usage(cible).free / 1024**3
    except OSError:
        libre = 0.0
    return Machine(
        memoire_go=round(memoire_go(), 1),
        disque_libre_go=round(libre, 1),
        acceleration=acceleration(),
    )


# --------------------------------------------------------------- Claude Code

def claude_installe() -> bool:
    return shutil.which("claude") is not None


def claude_version() -> str:
    if not claude_installe():
        return ""
    sortie = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                            check=False, timeout=20).stdout
    return sortie.strip().split()[0] if sortie.strip() else ""


def claude_authentifie() -> bool:
    """Vérifie que la session Claude Code existe.

    Sans authentification, Claude Code est installé mais incapable de rédiger
    quoi que ce soit — et l'erreur n'apparaîtrait qu'après une heure de
    transcription, au pire moment. On regarde le marqueur de session plutôt que
    d'appeler le modèle : la vérification doit être gratuite et instantanée.
    """
    fichier = Path.home() / ".claude.json"
    if not fichier.exists():
        return False
    try:
        contenu = json.loads(fichier.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(contenu.get("oauthAccount") or contenu.get("userID"))


@dataclass(frozen=True)
class CompteClaude:
    """Qui rédige, vu du poste. Lu du fichier de session, jamais du réseau."""

    adresse: str
    organisation: str
    formule: str

    def __str__(self) -> str:
        morceaux = [m for m in (self.adresse, self.organisation) if m]
        return " · ".join(morceaux) if morceaux else "session ouverte"


def compte_claude() -> CompteClaude | None:
    """Le compte Claude Code connecté, ou None si aucune session.

    On lit le marqueur de session plutôt que d'interroger l'API : la fenêtre
    affiche ce renseignement à chaque ouverture de l'onglet, et un appel réseau
    y ferait une attente là où il n'y a rien à attendre. Aucun jeton n'est lu,
    seulement de quoi reconnaître le compte.
    """
    fichier = Path.home() / ".claude.json"
    try:
        contenu = json.loads(fichier.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    compte = contenu.get("oauthAccount") or {}
    if not (compte or contenu.get("userID")):
        return None
    return CompteClaude(
        adresse=str(compte.get("emailAddress") or ""),
        organisation=str(compte.get("organizationName") or ""),
        formule=str(compte.get("seatTier") or compte.get("billingType") or ""),
    )


COMMANDE_INSTALLER_CLAUDE = {
    "Darwin": "curl -fsSL https://claude.ai/install.sh | bash",
    "Linux": "curl -fsSL https://claude.ai/install.sh | bash",
    "Windows": "irm https://claude.ai/install.ps1 | iex",
}


# ------------------------------------------------------------------- courriel

def outlook_present() -> bool:
    if SYSTEME != "Darwin":
        return False
    return Path("/Applications/Microsoft Outlook.app").exists()


# ----------------------------------------------------------------------- audio

def capture_systeme() -> Constat:
    """De quoi réenregistrer ce que jouent les haut-parleurs.

    C'est ce qui permet d'entendre les autres participants d'une visio. Le seul
    point où les trois systèmes divergent vraiment.
    """
    if SYSTEME == "Darwin":
        sortie = subprocess.run(["system_profiler", "SPAudioDataType"],
                                capture_output=True, text=True, check=False).stdout
        present = "BlackHole" in sortie
        return Constat(
            nom="Capture du son des autres participants",
            present=present,
            detail="BlackHole installé" if present else "BlackHole absent",
            remede="brew install --cask blackhole-2ch && sudo killall coreaudiod",
        )
    if SYSTEME == "Linux":
        present = shutil.which("pactl") is not None
        return Constat(
            nom="Capture du son des autres participants",
            present=present,
            detail="moniteur PipeWire/PulseAudio" if present else "pactl absent",
            remede="installe « pipewire-pulse » ou « pulseaudio-utils »",
        )
    return Constat(
        nom="Capture du son des autres participants",
        present=True,
        detail="boucle WASAPI intégrée à Windows",
    )


def micro_present() -> Constat:
    detail = ""
    present = False
    if SYSTEME == "Darwin":
        sortie = subprocess.run(["system_profiler", "SPAudioDataType"],
                                capture_output=True, text=True, check=False).stdout
        present = "Input" in sortie or "Micro" in sortie
        detail = "au moins une entrée audio détectée" if present else "aucune entrée audio"
    elif SYSTEME == "Linux":
        present = Path("/proc/asound/cards").exists() or shutil.which("pactl") is not None
        detail = "carte son détectée" if present else "aucune carte son"
    else:
        present = True
        detail = "supposé présent"
    return Constat(nom="Micro", present=present, detail=detail,
                   remede="branche un micro ou un casque", bloquant=True)


# ------------------------------------------------------------------ synthèse

@dataclass
class Diagnostic:
    machine: Machine
    constats: list[Constat] = field(default_factory=list)

    @property
    def bloquants(self) -> list[Constat]:
        return [c for c in self.constats if c.bloquant and not c.present]

    @property
    def manquants(self) -> list[Constat]:
        return [c for c in self.constats if not c.present]

    @property
    def pret(self) -> bool:
        return not self.bloquants


def examiner(dossier_donnees: Path | None = None) -> Diagnostic:
    """Tout ce qu'il faut savoir avant de configurer quoi que ce soit."""
    infos = machine(dossier_donnees)
    constats = [
        Constat(
            nom="ffmpeg", present=shutil.which("ffmpeg") is not None,
            detail="enregistrement et conversion audio",
            remede="brew install ffmpeg" if SYSTEME == "Darwin" else "installe ffmpeg",
            bloquant=True,
        ),
        micro_present(),
        capture_systeme(),
        Constat(
            nom="Claude Code", present=claude_installe(),
            detail=claude_version() or "absent",
            remede=COMMANDE_INSTALLER_CLAUDE.get(SYSTEME, ""),
        ),
        Constat(
            nom="Session Claude", present=claude_authentifie(),
            detail="authentifiée" if claude_authentifie() else "jamais connectée",
            remede="lance « claude » une fois et connecte-toi",
        ),
        Constat(
            nom="Mémoire vive", present=infos.supporte_grand_modele,
            detail=f"{infos.memoire_go:.0f} Go — modèle conseillé : {infos.modele_conseille}",
            remede="un modèle plus petit sera utilisé, la transcription sera moins fine",
        ),
        Constat(
            nom="Espace disque", present=infos.disque_libre_go >= DISQUE_NECESSAIRE_GO,
            detail=(f"{infos.disque_libre_go:.0f} Go libres, "
                    f"{DISQUE_NECESSAIRE_GO:.0f} Go nécessaires"),
            remede="libère de la place avant de télécharger les modèles",
            bloquant=True,
        ),
    ]
    return Diagnostic(machine=infos, constats=constats)
