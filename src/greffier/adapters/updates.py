"""Asking GitHub whether a version later than the installed one exists."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as version_du_paquet
from pathlib import Path
from typing import Any

from greffier.domain.version import is_newer

REPOSITORY = "tanguychenier/greffier"

TIMEOUT = 5.0

DELAI_TELECHARGEMENT = 600.0

ARTEFACTS = {
    "Darwin": "Greffier-macos.zip",
    "Windows": "Greffier-windows.zip",
    "Linux": "Greffier-linux.tar.gz",
}

@dataclass(frozen=True, slots=True)
class Verdict:
    """What the check learned. With `trouble` filled in, nothing is certain."""

    installed: str
    available: str = ""
    adresse: str = ""
    trouble: str = ""
    artefact: str = ""
    artefact_nom: str = ""

    @property
    def downloadable(self) -> bool:
        """True when there is a binary to install for this machine."""
        return bool(self.available and self.artefact)

    @property
    def up_to_date(self) -> bool:
        return not self.trouble and not self.available

    @property
    def update(self) -> bool:
        return bool(self.available)

    def say(self) -> str:
        """One sentence for the screen, in French, without jargon."""
        if self.trouble:
            return f"Vérification impossible : {self.trouble}"
        if self.available:
            return f"Version {self.available} disponible (vous avez {self.installed})."
        return f"À jour : version {self.installed}."

def installed_version() -> str:
    """The version of the bundle in place, or an empty string."""
    try:
        installed = version_du_paquet("greffier")
    except PackageNotFoundError:
        installed = ""
    depuis_les_sources = _version_du_projet()
    return depuis_les_sources or installed

def _version_du_projet() -> str:
    """The version written in pyproject.toml, when it can be reached."""
    projet = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if not projet.exists():
        return ""
    try:
        import tomllib

        with projet.open("rb") as flux:
            return str(tomllib.load(flux).get("project", {}).get("version", ""))
    except (OSError, ValueError):
        return ""

def build_repository() -> Path | None:
    """The repository this bundle was built from, if it is still there."""
    grave = os.environ.get("GREFFIER_DEPOT_SOURCE", "").strip()
    if not grave:
        return None
    path = Path(grave)
    return path if (path / "macos" / "construire.sh").exists() else None

def installable() -> tuple[bool, str]:
    """Can it install from here? If not, why."""
    store = build_repository()
    if store is None:
        return (False, "le dépôt d'origine est introuvable")
    if shutil.which("git") is None:
        return (False, "git est introuvable")
    state = subprocess.run(
        ["git", "-C", str(store), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    if state.returncode != 0:
        return (False, "ce dossier n'est pas un dépôt git")
    if state.stdout.strip():
        return (False, "le dépôt porte des modifications non validées")
    return (True, str(store))

_RELAIS = """#!/bin/bash
set -u
exec >>"$3" 2>&1
echo "=== mise à jour lancée le $(date '+%Y-%m-%d %H:%M:%S') ==="
for _ in $(seq 1 60); do
  kill -0 "$2" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$2" 2>/dev/null; then
  echo "✗ l'application n'a pas quitté : rien n'a été touché"
  exit 1
fi
cd "$1" || exit 1
git pull --ff-only || { echo "✗ git pull a échoué : le paquet est intact"; exit 1; }
bash macos/construire.sh || { echo "✗ la reconstruction a échoué"; exit 1; }
echo "✓ mis à jour, relancement"
open -a "$4"
"""

def install(app: str = "Greffier") -> tuple[bool, str]:
    """Starts the update relay, then hands back so we can close.

    Updates nothing by itself: it prepares, and the caller has to quit right after.
    The relay waits for this process to end before touching the bundle.
    """
    possible, because = installable()
    if not possible:
        return (False, because)

    log = Path.home() / "Library" / "Logs" / "Greffier-maj.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    script = Path(tempfile.gettempdir()) / "greffier-mise-a-jour.sh"
    script.write_text(_RELAIS, encoding="utf-8")
    script.chmod(0o755)
    try:
        subprocess.Popen(
            ["/bin/bash", str(script), because, str(os.getpid()), str(log), app],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as trouble:
        return (False, str(trouble))
    return (True, str(log))

def bundle_of_this_process(argv0: str = "") -> Path | None:
    """The .app bundle this process runs from, if there is one."""
    executable = Path(argv0 or sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent
    return None

def download(
    url: str, target: Path, timeout: float = DELAI_TELECHARGEMENT,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[bool, str]:
    """Writes the artifact to disk. Never raises.

    In chunks, reporting progress: this is a hundred and fifty megabytes, and a
    window that froze silently for two minutes passed for broken.
    """
    requete = urllib.request.Request(url, headers={"User-Agent": "Greffier"})
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(requete, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            recu = 0
            with target.open("wb") as output:
                while morceau := response.read(262144):
                    output.write(morceau)
                    recu += len(morceau)
                    if progress is not None:
                        progress(recu, total)
    except (urllib.error.URLError, TimeoutError):
        return (False, "pas de réseau")
    except (OSError, ValueError) as trouble:
        return (False, str(trouble))
    if target.stat().st_size == 0:
        return (False, "archive vide")
    return (True, str(target))

def unpack(archive: Path, folder: Path) -> tuple[bool, str]:
    """Opens the archive into a folder. Returns the path of what it holds."""
    import tarfile
    import zipfile

    try:
        folder.mkdir(parents=True, exist_ok=True)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(folder)
        elif archive.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive) as a:
                a.extractall(folder, filter="data")
        else:
            return (False, f"format inconnu : {archive.name}")
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as trouble:
        return (False, str(trouble))
    return (True, str(folder))

_RELAIS_BINAIRE = """#!/bin/bash
set -u
exec >>"$3" 2>&1
echo "=== mise a jour binaire lancee le $(date '+%Y-%m-%d %H:%M:%S') ==="
NEUF="$1"; PID="$2"; APP="$4"
for _ in $(seq 1 120); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$PID" 2>/dev/null; then
  echo "x l'application n'a pas quitte : rien n'a ete touche"
  exit 1
fi
[ -d "$NEUF" ] || { echo "x le paquet telecharge est introuvable"; exit 1; }
DE_COTE="$APP.precedent"
rm -rf "$DE_COTE"
mv "$APP" "$DE_COTE" 2>/dev/null || true
if ! mv "$NEUF" "$APP"; then
  echo "x remplacement impossible, ancienne version remise"
  mv "$DE_COTE" "$APP" 2>/dev/null || true
  exit 1
fi
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$APP" 2>/dev/null
open -a "$APP" || true
for _ in $(seq 1 24); do
  pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1 && break
  sleep 0.5
done
if pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; then
  echo "v mis a jour et relance"
  rm -rf "$DE_COTE"
else
  echo "x la nouvelle version ne demarre pas, ancienne version remise"
  rm -rf "$APP"
  mv "$DE_COTE" "$APP" 2>/dev/null || true
  open -a "$APP" || true
  exit 1
fi
"""

def install_from_release(
    verdict: Verdict, argv0: str = "",
    progress: Callable[[int, int], None] | None = None,
) -> tuple[bool, str]:
    """Downloads this system's artifact and puts it in place.

    This is the path for whoever does not have the repository: the vast majority.
    Nothing is compiled, nothing is cloned.
    """
    if not verdict.downloadable:
        return (False, "aucun binaire publié pour ce système")
    atelier = Path(tempfile.mkdtemp(prefix="greffier-maj."))
    archive = atelier / verdict.artefact_nom
    recu, ou = download(verdict.artefact, archive, progress=progress)
    if not recu:
        return (False, ou)
    ouvert, trouble = unpack(archive, atelier / "contenu")
    if not ouvert:
        return (False, trouble)

    if platform.system() != "Darwin":
        return (True, str(atelier / "contenu"))

    paquets = list((atelier / "contenu").glob("*.app"))
    if not paquets:
        return (False, "l'archive ne contient pas d'application")
    app = bundle_of_this_process(argv0)
    if app is None:
        return (False, "cette version ne tourne pas depuis un paquet")

    log = Path.home() / "Library" / "Logs" / "Greffier-maj.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    script = Path(tempfile.gettempdir()) / "greffier-maj-binaire.sh"
    script.write_text(_RELAIS_BINAIRE, encoding="utf-8")
    script.chmod(0o755)
    try:
        subprocess.Popen(
            ["/bin/bash", str(script), str(paquets[0]), str(os.getpid()),
             str(log), str(app)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as trouble:
        return (False, str(trouble))
    return (True, str(log))

def bundle_is_newer(argv0: str = "") -> bool:
    """Is the bundle on disk newer than the running process?"""

    executable = Path(argv0 or sys.executable)
    if "/Contents/MacOS/" not in str(executable):
        return False
    try:
        pose = executable.stat().st_mtime
        return pose > _CHARGE_LE
    except OSError:
        return False

_CHARGE_LE = time.time()

def check(store: str = REPOSITORY, timeout: float = TIMEOUT) -> Verdict:
    """Asks about the latest published release. Never raises."""
    installed = installed_version()
    if not installed:
        return Verdict(installed="", trouble="version installée inconnue")

    adresse = f"https://api.github.com/repos/{store}/releases/latest"
    requete = urllib.request.Request(
        adresse,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Greffier"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as response:
            content = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as trouble:
        if trouble.code == 404:
            return Verdict(installed=installed, trouble="aucune version publiée")
        return Verdict(installed=installed, trouble=f"réponse {trouble.code} de GitHub")
    except (urllib.error.URLError, TimeoutError):
        return Verdict(installed=installed, trouble="pas de réseau")
    except (ValueError, OSError) as trouble:
        return Verdict(installed=installed, trouble=str(trouble))

    if not isinstance(content, dict):
        return Verdict(installed=installed, trouble="réponse inattendue")
    label = str(content.get("tag_name", "")).strip()
    if not label:
        return Verdict(installed=installed, trouble="version publiée sans étiquette")
    if not is_newer(label, installed):
        return Verdict(installed=installed)
    name, url = _artifact_for_this_system(content)
    return Verdict(
        installed=installed,
        available=label.lstrip("v"),
        adresse=str(content.get("html_url", "")),
        artefact=url,
        artefact_nom=name,
    )

def _artifact_for_this_system(publication: dict[str, Any]) -> tuple[str, str]:
    """The name and address of the artifact that suits this system.

    The right one and no other: all three hang off the same release, and a Windows
    archive installed on a Mac would produce nothing that launches.
    """
    attendu = ARTEFACTS.get(platform.system(), "")
    if not attendu:
        return ("", "")
    for piece in publication.get("assets") or []:
        if not isinstance(piece, dict):
            continue
        if str(piece.get("name", "")) == attendu:
            return (attendu, str(piece.get("browser_download_url", "")))
    return ("", "")
